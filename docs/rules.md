# Rule reference

`specguard rules <name>` prints the same information for one checker.

Counting rules accept `min`, `max`, `exact` and `between: [lo, hi]`. `at_least`, `at_most` and `exactly` are synonyms. Text rules that scan the document also accept `exclude_code_blocks: true` and `exclude_sections: [Heading, ...]`. An excluded section runs from its heading to the next heading of the same or higher level.

## word_count

```yaml
checker: word_count
parameters:
  between: [1500, 2000]
  exclude_sections: [References]
  include_headings: true       # default
  include_tables: true         # default
  count_method: words          # or: whitespace
```

`words` counts runs of letters and digits; a hyphenated word or `don't` counts once, `1,500` counts once, and `—` or Markdown markers are not words. `whitespace` counts space-separated chunks, closer to Microsoft Word. Neither includes DOCX text boxes, headers or footnotes.

## forbidden_text / required_text

```yaml
checker: forbidden_text
parameters:
  values: [delve, "in conclusion"]
  case_sensitive: false        # default
  whole_word: false            # default; true stops "art" matching "article"
```

`required_text` adds `require: all | any`. Spaces in a phrase match any whitespace, so a phrase still matches across a hard line wrap. Markdown emphasis and links are removed before matching.

`required_text` also takes `within: first_paragraph | last_paragraph` (default `document`). A paragraph here is body text: headings, list items, tables and code blocks do not count. If the document has no body paragraph the result is UNVERIFIED.

## forbidden_regex / required_regex

```yaml
checker: forbidden_regex
parameters:
  pattern: '\[(?:insert|tbc)[^\]]*\]'
  flags: [ignorecase]          # ignorecase, multiline, dotall
```

Patterns match inside one paragraph or table cell. Patterns longer than 1,000 characters, invalid patterns, and patterns that can match the empty string are rejected at validation. Matching runs under a 2-second timeout.

## occurrences

```yaml
checker: occurrences
parameters:
  text: climate change         # or: pattern: 'v\d+'
  min: 2
```

## element_count

```yaml
checker: element_count
parameters:
  element: references          # bullets | numbered_items | list_items | headings |
  min: 30                      # tables | code_blocks | paragraphs | references
```

`references` counts the paragraphs and list items under a heading named References, Reference list, Bibliography or Works cited (override with `section_names`). It assumes one entry per paragraph, so its results carry a confidence below 1 and say so. `headings` accepts `level: 2`.

## required_section

```yaml
checker: required_section
parameters:
  headings:
    - Introduction
    - [Methodology, Methods]   # a nested list means "any of these"
    - Conclusion
  require: all                 # default
  exact: true                  # default; false = the name may appear inside a longer heading
  case_sensitive: false        # default
```

Numbering such as `2.1` or `Chapter 3:` and a trailing colon are ignored when comparing. Only real headings count: `#` in Markdown, Heading styles in Word, and (in plain text) `#`, an underline of `=`/`-`, numbering, or ALL CAPS. In plain text a short standalone line with no full stop is also accepted, with a note and reduced confidence. On failure the report lists the headings that do exist and suggests near matches.

`ordered: true` (with `require: all`) also requires the headings to appear in the order listed; a missing heading is still reported as missing, and an out-of-order set fails with the order that was found.

## spelling_variant

```yaml
checker: spelling_variant
parameters:
  variant: british             # or american
  allow: [Color]               # optional: words to ignore, such as a proper name
```

A word-list check, not a spell checker. It looks for spellings of the *other* variant from a built-in list of common pairs (`color`/`colour`, `center`/`centre`, `analyze`/`analyse`, `traveled`/`travelled`, and `-ise`/`-ize` stems), including common endings. A failure names the words and places. A pass has confidence 0.75, because words that are not on the list are not examined, and the evidence says how many pairs were checked. `-ize` is never reported in a British document (Oxford spelling); `-ise` is reported in an American one. Matches inside double quotation marks are not counted, because a title or quotation keeps its own spelling; they are listed in the evidence and in `details.ignored_in_quotes`.

## forbidden_punctuation

```yaml
checker: forbidden_punctuation
parameters:
  marks: [em_dash, ";"]
  max_allowed: 0               # total across all marks
```

Names: `em_dash`, `en_dash`, `semicolon`, `exclamation_mark`, `ellipsis`, `colon`, `double_hyphen`, `ampersand`, `curly_quotes`. Spelling variants (`em dash`, `em-dashes`) work. Any literal character also works. Nothing is forbidden unless you list it.

## preserve_text

See [specification.md](specification.md#protected-text). Options: `case_sensitive` (default true), `normalize_whitespace` (default true), `normalize_quotes` (default false; a curly quote is a change).

## file_type

```yaml
checker: file_type
parameters:
  extensions: [docx]
```

## docx_format

```yaml
checker: docx_format
parameters:
  margin_cm: 2.54              # or margins_cm: {top: 2.54, left: 3.0}
  orientation: portrait
  font_name: Times New Roman   # default (Normal) style
  font_size_pt: 12
  line_spacing: 1.5
```

Reads page setup and the Normal style only. If the file does not set a value (it is inherited from the theme), the result is UNVERIFIED rather than a guess. On non-DOCX files the result is UNVERIFIED.

## Locations in reports

- Markdown and text: `line 72`, `paragraph 14`, `table 3, row 4, column 2`, and the enclosing heading.
- DOCX: `paragraph 14` counts non-empty body paragraphs in order; tables are `table N, row R, column C`. There are no line numbers.
