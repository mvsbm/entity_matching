[README](../../README.md) · **Guide:** [1 Task](01-entity-resolution-and-our-task.md) · **2 Variants** · [3 Pairs](03-far-too-many-pairs.md) · [4 Rules](04-certain-cases-first-rules.md) · [5 Evidence](05-uncertain-evidence-fellegi-sunter.md) · [6 Measuring](06-measuring-and-choosing.md)

# 2. The same fact, written differently

*Challenges C1 (variants) and C2 (Japanese text).*

Before two records can be compared, they must say the same thing in the same way. This chapter covers three challenges, in order: spelling and format variants, measuring "how close", and the trap that Japanese text sets for standard tools.

## Challenge: the same fact, many spellings

Staff type what they hear and what they see. In our validation file, one man appears as マツモトヒサオ on one record and マツモトヒサウ on another. One address arrives in three forms:

| Typed as | Why it differs |
|---|---|
| 東京都千代田区丸の内1丁目3番17号 | written out with 丁目, 番 and 号 |
| 千代田区丸の内１－３－１７ | no prefecture, full-width digits |
| 東京都千代田区丸の内1-3-17　サクラハイツ101 | a building and a room number |

Compared as raw text, these are three different addresses.

### Solution: normalize before comparing

A *normalizer* maps every variant of one fact to one standard form. We use three.

**Kana folding** maps similar-sounding katakana to one form: voiced to unvoiced (ガ → カ), small to large (ッ → ツ), and the long-vowel mark to a vowel (ー → ウ).

| Name | Folded |
|---|---|
| ガトウユリゴ | カトウユリコ |
| コバヤシ | コハヤシ |
| サトー | サトウ |

**Address parsing** turns any typed address into one key. It converts full-width characters to normal ones, drops the prefecture, rewrites 丁目, 番 and 号 as dashes, and cuts off the building. All three addresses above become `千代田区丸の内1-3-17`.

**Company names** lose their legal form before comparing: カブシキガイシャカネコカイソウテン becomes カネコカイソウテン.

### Why this solution

- **Similarity alone can't bridge format changes.** `1丁目3番17号` and `1-3-17` are many edits apart, although they mean the same thing.
- **It stays readable.** Every rule is one line in `config/settings.toml`. Anyone can see exactly which forms get merged.
- **Alternatives need labels.** A learned model of "same address" would need many labelled examples, and we have none.

### Filling the gaps: derived columns

A record may have a full name, or only a surname and a given name in separate columns. So we build **derived columns** that take the first available source:

| Derived column | Takes the first filled of |
|---|---|
| `PERSON_NAME` | full name → original full name → surname + given name |
| `POSTAL` | postal code → postal code (kana form) |
| `ADDRESS` | standardized address → address as typed |

A derived column is filled more often than any of its sources. That matters, because an empty field gives no evidence at all ([chapter 5](05-uncertain-evidence-fellegi-sunter.md)).

### What it costs

Normalizing is not perfectly safe:

- **Folding can merge different names.** ショウジ and ショウシ are different names, but both fold to シヨウシ. That's why a folded match counts for a little less than an exact one ([chapter 5](05-uncertain-evidence-fellegi-sunter.md)).
- **Cutting the building merges neighbours.** Two flats in one building get the same address key. Different households at one address are a known source of look-alikes.

**In short:** normalize first, so that the same fact is written once.

## Challenge: how close is "close"?

After folding, マツモトヒサオ and マツモトヒサウ still differ in one character. We need a number that says how close two strings are.

### Solution: a similarity function for each kind of field

| Function | What it measures | マツモトヒサオ vs マツモトヒサウ | Cost per pair |
|---|---|---|---|
| exact | equal or not | not equal | constant, using a hash |
| Levenshtein | the fewest single-character edits from one to the other | 1 edit | O(m·n) |
| Jaro–Winkler | shared characters in a similar order, with a bonus for a shared start | 0.943 | O(m·n) |
| Jaccard | shared characters, ignoring order: \|A ∩ B\| / \|A ∪ B\| | 6 / 8 = 0.75 | O(m + n) |
| Hamming | positions that differ, for strings of equal length | (phones 0599 vs 0499: 1) | O(n) |

Here m and n are the two string lengths. Names are short, so even O(m·n) is cheap.

**How Jaro–Winkler reaches 0.943.** Both names have 7 characters, and 6 of them match in the same order, with no swaps. The Jaro score averages three ratios: matches in the first string, matches in the second, and matches in the right order:

$$J = \tfrac{1}{3}\left(\tfrac{6}{7} + \tfrac{6}{7} + \tfrac{6}{6}\right) = 0.905$$

Winkler then rewards a shared start, because typing errors are rarer at the beginning. The two names share their first 4 characters (マツモト), so:

$$JW = J + 4 \times 0.1 \times (1 - J) = 0.905 + 0.038 = 0.943$$

### Why each field gets its own function

- **Names use Jaro–Winkler.** Japanese names start with the surname, and the shared start earns a bonus. So a typo late in the given name still scores high.
- **Addresses use edit distance.** A wrong digit or a dropped character is one edit.
- **Phones use Hamming distance.** The last four digits have a fixed length, so one wrong digit is distance 1.
- **Company names can use Jaccard.** The legal form comes either first or last: カブシキガイシャ… or …カブシキガイシャ. Jaccard ignores order, so both forms score the same. The rules stage adopted it for this reason ([chapter 4](04-certain-cases-first-rules.md)).

The exact thresholds (for example, "Jaro–Winkler at least 0.95") are chosen per stage, by rule ([chapter 6](06-measuring-and-choosing.md)).

**In short:** pick the similarity that matches how each field goes wrong.

## Challenge: Japanese text breaks standard tools

DuckDB, the database engine under Splink, has built-in similarity functions. They compare **bytes**, not characters. In UTF-8, each katakana character takes 3 bytes. Every katakana shares the same first byte, and most share the second as well. Byte by byte, unrelated names look far more alike than they are:

| Pair | Byte-level Jaro–Winkler | Character-level |
|---|---|---|
| サトウヒロシ vs サトウタカシ (two different people) | 0.897 | 0.844 |
| マツモトヒサオ vs マツモトヒサウ (one person) | 0.981 | 0.943 |

### Solution: character-level versions of every function

`er/strings.py` registers character-level versions of each function in DuckDB, built on the `rapidfuzz` library. They are named `cl_jaro_winkler`, `cl_levenshtein`, and so on. Every rule and every model level uses them. `connect()` checks them on every start, and so do the tests.

### Why it matters

The gap is not cosmetic. Our model treats Jaro–Winkler at or above 0.95 as "very close", worth far more evidence than "close". The byte-level score of 0.981 would lift this pair over that line. Every katakana pair would look closer than it really is.

**In short:** count characters, not bytes.

## In the code

- `config/settings.toml`, section `[standardize]`: the folding table, legal forms, address rules, derived columns
- `er/standardize.py`: `normalize` (apply named normalizers), `prepare` (derive and normalize the columns a stage uses)
- `er/strings.py`: `cl_*` functions, `connect()`
- `tests/test_er.py`: character-level and NULL-safe functions; the three address formats give one key

## Further reading

- P. Christen, *Data Matching*, Springer, 2012: chapter 3 (data pre-processing) and chapter 5 (field and record comparison).
- W. E. Winkler, "String comparator metrics and enhanced decision rules in the Fellegi–Sunter model of record linkage," *Proceedings of the Section on Survey Research Methods*, American Statistical Association, 1990. The origin of Jaro–Winkler.
- [rapidfuzz documentation](https://rapidfuzz.github.io/RapidFuzz/): the string metrics behind `cl_*`.

**Next:** [3. Far too many pairs →](03-far-too-many-pairs.md)
