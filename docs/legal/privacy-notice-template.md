# Privacy notice — template

> **This is a template, not legal advice.** It describes what Polyglot
> Swarm's code does with personal data as of this version, so that an
> operator and their counsel can turn it into a notice that fits their
> service and jurisdiction. Replace every `<...>`, delete what does not
> apply to your configuration, and have it reviewed by qualified counsel
> before publishing. The data inventory it is based on is in
> [`docs/production/security-privacy-review.md`](../production/security-privacy-review.md).

---

# Privacy notice for `<service name>`

Last updated: `<date>`

`<Operator legal name>` ("we") runs `<service name>`, a language-learning
tutor at `<https://your-domain>`. This notice explains what personal data
we process, why, who receives it, how long we keep it, and your rights.

**Contact:** `<privacy contact email>` · `<postal address>`
`<Data protection officer or EU/UK representative, if you need one>`

## Who can use the service

`<Choose one, with counsel: "You must be at least <age> to use the service." / describe how parental consent works if minors are admitted.>`

## What we collect

| Data | Examples | Why |
|---|---|---|
| Account data | username, password (stored only as a salted hash) | to give you an account and keep it secure |
| What you write and say in lessons | chat messages, answers, transcripts of your speaking practice | to run the lessons and give feedback |
| Your learning record | the skills, words and grammar the tutor has seen you use, your review schedule, level estimates | to plan what you practice next; this is the core of the service |
| Voice recordings | `<only if voice is enabled>` recordings of speaking exercises. We **do not keep the audio** unless you choose to; if you do, it is deleted after **30 days** | to assess pronunciation and fluency |
| Technical data | request logs without lesson content, usage counters, model call statistics | security, reliability, cost control |

We do not use advertising trackers, and we do not sell personal data.

## Automated assessment

The tutor builds an automated model of your language skills from your
lessons (your "learner model") and uses it to choose exercises and to
estimate your level. It does not make decisions with legal or similarly
significant effects. `<Counsel: confirm whether this is "profiling" in your jurisdiction and what you must state about it.>`

## Who receives your data

| Recipient | What | When |
|---|---|---|
| `<AI provider(s) you enable: Anthropic / Google / OpenAI>` | your lesson messages and recent conversation context, without your account details | each lesson turn and analysis. `<Delete this row if you run with LOCAL_ONLY=true.>` |
| Microsoft (Edge text-to-speech) | the text the tutor speaks aloud, without your account details | `<only if voice is enabled>` |
| `<Off-host backup storage provider>` | encrypted backup copies. The data is encrypted on our servers before upload, and the provider cannot read it | every hour |
| `<Hosting provider>` | everything above, as our infrastructure provider | always |

`<International transfers: name the countries and the safeguards (e.g. standard contractual clauses), with counsel.>`

## How long we keep it

| Data | Retention |
|---|---|
| Account, lesson content, learning record | until you delete your account or your data |
| Retained voice recordings | 30 days |
| Usage counters, model call statistics | up to 90 days |
| Backups | up to 2 days on our server and up to **30 days** in encrypted off-site backups. If you delete your data, it disappears from backups when they expire |

## Your rights

You can **download all your data** and **permanently delete your account
and data** at any time in the app, under *Your data*. You can also contact
us at `<privacy contact email>`
`<operators: "polyglot privacy" on the host serves requests that arrive by email>`
to exercise your rights `<list the rights that apply, e.g. access, rectification, erasure, restriction, portability, objection, and the right to complain to <supervisory authority>>`.

## Legal basis

`<With counsel: the lawful basis for each purpose above, e.g. contract for running lessons, legitimate interests for security, consent for retaining voice recordings.>`

## Security

Passwords and sign-in tokens are stored only as hashes. Access to your
data is limited to your own account. Backups are verified and copied
off-site in encrypted form. See `<link to your security contact or SECURITY.md>`
to report a vulnerability.

## Changes

We will post changes here and update the date above. `<Describe how you notify users of material changes.>`
