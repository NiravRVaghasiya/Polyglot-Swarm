# Language packs

Polyglot Swarm's agents work with **any** language name out of the box (the
LLM prompts are generic — "You are an expert {language} grammar analyzer").
A language pack adds versioned, reviewable linguistic resources on top of
that generic capability for a specific language: frequency-ranked
vocabulary, a grammar construction taxonomy, collocations, register notes,
and cross-language transfer data. A pack is optional — a language with no
pack still works through the generic agents; a pack makes specific agents
(vocabulary difficulty, grammar taxonomy references, transfer suggestions)
sharper for that language.

## Supported packs today

Three languages ship a pack: **Spanish (`es`)**, **Polish (`pl`)**, **Italian
(`it`)** — the mapping lives in `src/languages/paths.py`'s `NAME_TO_CODE`.
`pack_code(language)` accepts either the full name or the raw code
(case-insensitive); an unrecognized language returns `None`, and every
pack-consuming function degrades to an empty result rather than raising.

## On-disk layout

```
languages/<code>/
├── metadata.yaml                 # family, dialect, writing system, notes
├── grammar/
│   └── constructions.yaml        # the grammar taxonomy for this language
├── frequency/
│   └── frequency.txt             # one word per line, most-frequent first
├── collocations/
│   └── collocations.yaml         # fixed multi-word units
├── register/
│   └── register.yaml             # formality/register notes
└── transfer/
    └── <other_code>.yaml         # cognates/false-friends vs. another language
```

**Every file is optional.** `src/languages/pack.py`'s `load_pack(language)`
(memoized with `functools.cache`) assembles a `LanguagePack` from whatever
subset of files exists — a missing file yields an empty list/default for
that section, not an error. This is what lets a contributor add, say, only a
frequency list for a new language and have it picked up immediately without
touching any other file.

### `metadata.yaml`

```yaml
language: Spanish
code: es
family: Romance
dialect: Castilian
writing_system: Latin
notes: Free-text notes surfaced to whoever inspects the pack.
```

### `grammar/constructions.yaml`

Each entry is one grammar construction with a stable id, a CEFR level, an
explanation, examples, prerequisite constructions, and free-text notes on
cross-language interference:

```yaml
constructions:
  - construction: ser_vs_estar
    cefr: A2
    explanation: "..."
    examples: ["..."]
    prerequisites: []
    common_interferences: ["Italian/Polish learners often default to..."]
```

Loaded via `src.languages.grammar_taxonomy.list_constructions(language)`,
which `pack.py`'s `grammar_constructions(language)` re-exports.

### `frequency/frequency.txt`

One word per line, most frequent first; lines starting with `#` are
comments and skipped. `pack.py`'s `frequency_rank(language, word)` returns
the word's 1-based rank (lower = commoner), or `None` if the pack or word is
absent.

### `collocations/collocations.yaml` and `register/register.yaml`

Fixed multi-word units and formality notes, respectively — each entry maps
to a `CollocationItem`/`RegisterNote` pydantic model
(`src/llm/schemas.py`). Loaded via `collocations_for(language)` /
`register_notes_for(language)`.

### `transfer/<other_code>.yaml`

Cross-language transfer data consumed by `src/languages/transfer_graph.py`:
cognates (word pairs), false friends, and interference notes between this
language and `<other_code>`. This is deliberately a
**linguistic-resource-first design, not embedding similarity** — transfer
candidates come from this file plus a cheap orthographic heuristic;
`src/agents/transfer.py` only asks an LLM to *verify* candidates the
resource already proposed, never to invent them from scratch.
`candidates_for_word()` does exact, case-insensitive matching against the
loaded resource file — no fuzzy matching at this layer. Transfer files are
cached per `(source, target)` pair via `functools.cache`.

## Adding a new language pack

1. Add the language's name → code mapping to `NAME_TO_CODE` in
   `src/languages/paths.py`.
2. Create `languages/<code>/` and add any subset of the files above. Start
   with just `frequency/frequency.txt` or `metadata.yaml` if that's all you
   have — the rest will simply be empty until filled in.
3. No other code changes are required — every consumer of a pack already
   handles partial/missing packs.
4. If you're adding transfer data, name the file after the *target*
   language's code (`languages/es/transfer/it.yaml` for Spanish→Italian).

See [`CONTRIBUTING.md`](../CONTRIBUTING.md) for the PR process, and open an
issue first if you're proposing a new supported language rather than adding
resources to an existing one.
