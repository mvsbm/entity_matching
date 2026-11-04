[README](../../README.md) · **Guide:** [1 Task](01-entity-resolution-and-our-task.md) · **2 Variants** · [3 Pairs](03-far-too-many-pairs.md) · [4 Rules](04-certain-cases-first-rules.md) · [5 Evidence](05-uncertain-evidence-fellegi-sunter.md) · [6 Measuring](06-measuring-and-choosing.md)

# 2. The same fact, written differently

*Challenges C1 (variants) and C2 (Japanese text).*

Before two records can be compared, they must say the same thing in the same way. This chapter covers three challenges, in order: spelling and format variants, measuring "how close", and the trap that Japanese text sets for standard tools.

## Challenge: the same fact, many spellings

The same fact rarely reaches the database in the same form. Katakana names lose voicing marks or get small kana typed full-size, and addresses are typed in whatever format the clerk prefers. In our validation file, one man appears as マツモトヒサオ on one record and マツモトヒサウ on another. One address arrives in three forms:

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

After folding, マツモトヒサオ and マツモトヒサウ still differ in one character. We need a number that says how close two strings are. The right number depends on **how the field goes wrong**. A phone number goes wrong differently from a name, so each field gets a function built for its kind of mistake.

The functions come in four families:

| Family | Functions | The question each asks |
|---|---|---|
| edits | Levenshtein, Damerau–Levenshtein, Hamming | how many keystrokes turn one string into the other? |
| character matching | Jaro, Jaro–Winkler | how many characters do they share, in about the same order? |
| sets | Jaccard | how many of their characters do they share, in any order? |
| equality | exact | are they the same? |

### Levenshtein distance: counting edits

**The idea.** It counts the fewest single-character edits that turn one string into the other. An edit is inserting, deleting or replacing one character.

**How it is computed.** Fill a table. Cell (i, j) holds the distance between the first i characters of one string and the first j characters of the other. Each cell takes the cheapest of three moves: delete, insert, or replace. Replacing is free when the two characters are already equal:

$$d(i,j) = \min\big\{\, d(i-1,j)+1,\;\; d(i,j-1)+1,\;\; d(i-1,j-1) + [\,a_i \ne b_j\,] \,\big\}$$

For サトウ and サトオ:

| | "" | サ | ト | オ |
|---|---|---|---|---|
| **""** | 0 | 1 | 2 | 3 |
| **サ** | 1 | **0** | 1 | 2 |
| **ト** | 2 | 1 | **0** | 1 |
| **ウ** | 3 | 2 | 1 | **1** |

Along the diagonal the cost stays at 0 while the characters agree. The last step replaces ウ with オ, so the distance, in the bottom-right cell, is **1**.

**Properties:**
- Every edit costs 1, wherever it happens and however long the strings are.
- The result is a whole number: 0 means identical.
- It takes O(m·n) time for strings of lengths m and n.

**Where we use it, and why:**
- **Addresses in the model** ("address close": at most 2 edits). After normalization, an address error is usually a wrong or dropped digit. `千代田区丸の内1-3-17` and `1-3-7` are 1 edit apart, and a limit of 2 allows for one more slip.
- **Names in the rules** (folded names at most 2 edits apart). A rule always needs two more fields to agree exactly as well, so a simple count is safe there.

**Its blind spot.** Every edit costs the same, so it can't tell a slip in a long name from one in a short name. サトウ / サトオ and マツモトヒサオ / マツモトヒサウ are both 1 edit apart. But one kana is a third of サトウ and only a seventh of マツモトヒサオ. That's why the model uses Jaro–Winkler for names.

### Damerau–Levenshtein distance: a swap counts once

**The idea.** It is Levenshtein plus one more edit: swapping two neighbouring characters counts as a single edit.

**Example.** In 0599 and 0959, the 5 and the 9 have traded places. Levenshtein needs two replacements (distance 2). Damerau–Levenshtein needs one swap (distance **1**).

**Where we use it, and why.** **Phones in the rules** (at most 1). Typing two digits in the wrong order is one of the most common keying slips. It should count as one mistake, not two.

### Hamming distance: positions that differ

**The idea.** For two strings of the same length, it counts the positions where they differ.

**Example.** In 0599 and 0499, only the second digit differs, so the distance is **1**. The swap 0599 / 0959 counts **2**. Strings of different lengths have no Hamming distance at all.

**Properties.** It is the simplest and fastest function, O(n). It allows replacements only, never insertions or deletions.

**Where we use it, and why.** **Phones in the model** (the level "one digit off"). The last four digits always have exactly four characters, and the most common error is one wrong digit, which is exactly Hamming distance 1.

It also makes the evidence easy to check by counting. Each number has 4 × 9 = 36 neighbours at distance 1. So two strangers land there by chance about 36 times in 10,000, which is the 1 in 279 the model learned ([chapter 5](05-uncertain-evidence-fellegi-sunter.md)).

### Jaro and Jaro–Winkler: shared characters, in order, with a bonus for the start

**The idea.** Two strings are similar if they share many characters in roughly the same order, especially at the start. The score runs from 0 (nothing shared) to 1 (identical).

**How Jaro counts:**

1. **Matches.** A character in one string *matches* an equal character in the other if the two are at most w positions apart:

   $$w = \left\lfloor \frac{\max(|a|,\,|b|)}{2} \right\rfloor - 1$$

   Each character can match only once. The number of matches is m.

2. **Transpositions.** Read the matched characters of each string in order, and count the positions where the two sequences disagree. Half that count is t.

3. **The score** averages three shares: the share of the first string that matched, the share of the second, and the share of matches in the right order.

   $$J = \frac{1}{3}\left(\frac{m}{|a|} + \frac{m}{|b|} + \frac{m - t}{m}\right)$$

**Winkler's bonus.** William Winkler observed that typing errors are less common at the start of a name. So a shared start of ℓ characters, counted up to 4, pulls the score towards 1:

$$JW = J + 0.1\,\ell\,(1 - J)$$

**Worked examples:**

| Pair | Window w | Matches m | Transpositions t | Jaro | Shared start ℓ | Jaro–Winkler |
|---|---|---|---|---|---|---|
| マツモトヒサオ / マツモトヒサウ | 2 | 6 | 0 | 0.905 | 4 | **0.943** |
| サトウ / サトオ | 0 | 2 | 0 | 0.778 | 2 | **0.822** |
| マツモト / マツトモ | 1 | 4 | 1 | 0.917 | 2 | **0.933** |

- **First row.** マ ツ モ ト ヒ サ match, but オ and ウ don't, and nothing is out of order. So $J = \tfrac13(\tfrac67 + \tfrac67 + \tfrac66) = 0.905$. The shared start マツモト lifts it to $0.905 + 0.1 \times 4 \times 0.095 = 0.943$.
- **Second row.** The window is 0, so characters can match only in the same position. サ and ト match, giving $J = \tfrac13(\tfrac23 + \tfrac23 + \tfrac22) = 0.778$.
- **Third row.** モ and ト are swapped. All four characters match, but read in order (マツモト vs マツトモ) two positions disagree, so t = 1 and $J = \tfrac13(1 + 1 + \tfrac34) = 0.917$.

**Properties:**
- **It is relative to length.** One slip in a long name costs less than one in a short name: 0.943 against 0.822 above, although both are a single edit.
- **It is forgiving at the end and strict at the start.**
- **It runs in O(m·n)** in the worst case. Names are short, so it is cheap.

**Where we use it, and why.** **Names in the model:** "very close" at 0.95 or more, "close" at 0.75 or more. Matt Jaro and William Winkler designed it at the US Census Bureau for exactly this job: comparing personal names with typing errors. Three of its properties fit our names:
1. It judges a slip against the length of the name, as a person would.
2. The first character is the one people most often get right. Folding has already removed the kana variants that do touch it, such as ガトウ → カトウ.
3. Japanese names start with the surname, so the shared start is usually the shared surname.

The rules also use Jaro–Winkler for addresses (0.91 or more). A normalized address shares a long start, the city and town, and differs, if at all, near the end.

**Its blind spot.** Different people who share a surname score high. サトウヒロシ and サトウタカシ reach **0.844**, which counts as "close" (at least 0.75). That's why "close" is weak evidence in the model, worth only about 4 bits ([chapter 5](05-uncertain-evidence-fellegi-sunter.md)).

### Jaccard similarity: shared characters, in any order

**The idea.** Treat each string as a *set* of characters, and measure how much the two sets overlap:

$$\text{Jaccard}(A, B) = \frac{|A \cap B|}{|A \cup B|}$$

The score runs from 0 (no character in common) to 1 (the same characters).

**Example.** マツモトヒサオ and マツモトヒサウ share 6 characters (マツモトヒサ), out of 8 distinct characters in total (adding オ and ウ). So the score is 6 / 8 = **0.75**.

**Properties.** It ignores order and repetition entirely, and runs in O(m + n).

**Where we use it, and why.** **Raw company names in the rules** (0.77 or more). A company's legal form can come first or last:

| Pair | Levenshtein | Jaro–Winkler | Jaccard |
|---|---|---|---|
| カブシキガイシャカネコカイソウテン / カネコカイソウテンカブシキガイシャ | 16 | 0.513 | **1.000** |

To the order-sensitive functions, the same company looks completely different. To Jaccard, it looks identical.

**Its blind spot, and why we use it nowhere else.** Because order doesn't count, Jaccard is the wrong tool for numbers. 0599 and 0959 have the same digits, so their Jaccard is 1.0. So do `千代田区丸の内1-3-17` and `1-3-7`, which may be a different address. For phones and addresses, the order *is* the information.

### Exact equality: for identifiers

**The idea.** Two values are equal after normalization, or they aren't.

**Where we use it, and why.** For the CIF ID, the address code and the postal code, and as the strongest level of every comparison. These are identifiers, not words: a code one digit away is usually a different code, so "nearly equal" carries no meaning. Exact matching is also the cheapest test, because the database finds equal values with a hash join ([chapter 3](03-far-too-many-pairs.md)).

### All the functions side by side

| Pair | What happened | Levenshtein | Damerau–Lev. | Hamming | Jaro–Winkler | Jaccard |
|---|---|---|---|---|---|---|
| マツモトヒサオ / マツモトヒサウ | one kana wrong, long name | 1 | 1 | 1 | 0.943 | 0.750 |
| サトウ / サトオ | one kana wrong, short name | 1 | 1 | 1 | 0.822 | 0.500 |
| マツモトヒサオ / マツモヒサオ | one kana dropped | 1 | 1 | — | 0.967 | 0.857 |
| マツモト / マツトモ | two kana swapped | 2 | 1 | 2 | 0.933 | 1.000 |
| サトウヒロシ / サトウタカシ | different people, same surname | 2 | 2 | 2 | 0.844 | 0.500 |
| カブシキガイシャカネコカイソウテン / カネコカイソウテンカブシキガイシャ | legal form moved | 16 | 16 | 16 | 0.513 | 1.000 |
| 0599 / 0499 | phone, one digit wrong | 1 | 1 | 1 | 0.850 | 0.500 |
| 0599 / 0959 | phone, two digits swapped | 2 | 1 | 2 | 0.925 | 1.000 |
| 福島市吉倉4-11 / 福島市吉倉4-17 | address, a digit wrong, or the neighbour | 1 | 1 | 1 | 0.956 | 0.889 |
| 千代田区丸の内1-3-17 / 千代田区丸の内1-3-7 | address, a digit dropped | 1 | 1 | — | 0.985 | 1.000 |

Reading down each column shows what each function notices:
- **The edit distances** see every slip, but not how big it is relative to the string.
- **Jaro–Winkler** sees the short-name slip as bigger, and still rates the different-people pair as fairly close.
- **Jaccard** ignores order. That rescues the moved legal form and ruins the swapped digits.

### Match the function to how the field goes wrong

| Field | How it goes wrong | Function | Why this one | Stage |
|---|---|---|---|---|
| person name | a kana wrong or dropped (spelling variants are folded first) | Jaro–Winkler: ≥ 0.95 very close, ≥ 0.75 close | judges a slip against the name's length, and rewards the shared surname at the start | model |
| | | Levenshtein ≤ 2, on folded names | a simple count, safe because the rule also needs the address code and phone | rules |
| company name | the legal form before or after the name | Jaccard ≥ 0.77, on raw names | order doesn't matter | rules |
| | a kana wrong | Jaro–Winkler, with the legal form removed | as for person names | model |
| address | a digit wrong or dropped (formats are normalized first) | Levenshtein ≤ 2 | one slip is one edit | model |
| | | Jaro–Winkler ≥ 0.91 | a long shared start (city, town), with any difference at the end | rules |
| phone (last 4) | one digit wrong | Hamming = 1 | fixed length, so one wrong digit is exactly distance 1 | model |
| | two digits swapped | Damerau–Levenshtein ≤ 1 | a swap counts as one slip | rules |
| CIF ID, address code, postal code | none in the generator | exact | an identifier has no "nearly" | both |

**A risk we accept, and how we contain it.** "Close" addresses include neighbours. 福島市吉倉4-11 and 4-17 score 0.956 and are one edit apart, whether through a typo or because they are next door. So a close address is never enough on its own:
- **In the rules,** a close address must come with a close name and the same phone.
- **In the model,** "address close" is worth +8.9 bits, against +14.0 for the same address.

### Other options, and why we didn't take them

- **Phonetic codes** such as Soundex give names that sound alike the same code. They were built for English, where spelling and sound often disagree. Katakana is already a phonetic script, and folding does the remaining work.
- **Weighted edits** could make ガ → カ cost less than ガ → サ. Folding gets the same effect more simply: confusable kana become equal before any comparison.
- **Character pieces with TF-IDF** compare names by shared fragments, weighting rare fragments more. We use them to *find* candidates ([chapter 3](03-far-too-many-pairs.md)), where speed over many names matters more than a precise score.

**In short:** give each field the function whose idea of a small mistake matches how that field really goes wrong.

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
- V. I. Levenshtein, "Binary codes capable of correcting deletions, insertions, and reversals," *Soviet Physics Doklady* 10(8), 1966.
- F. J. Damerau, "A technique for computer detection and correction of spelling errors," *Communications of the ACM* 7(3), 1964.
- R. W. Hamming, "Error detecting and error correcting codes," *Bell System Technical Journal* 29(2), 1950.
- M. A. Jaro, "Advances in record-linkage methodology as applied to matching the 1985 census of Tampa, Florida," *Journal of the American Statistical Association* 84(406), 1989.
- W. E. Winkler, "String comparator metrics and enhanced decision rules in the Fellegi–Sunter model of record linkage," *Proceedings of the Section on Survey Research Methods*, American Statistical Association, 1990. The prefix bonus.
- P. Jaccard, "The distribution of the flora in the alpine zone," *New Phytologist* 11(2), 1912. The origin of the Jaccard index.
- [rapidfuzz documentation](https://rapidfuzz.github.io/RapidFuzz/): the string metrics behind `cl_*`.

**Next:** [3. Far too many pairs →](03-far-too-many-pairs.md)
