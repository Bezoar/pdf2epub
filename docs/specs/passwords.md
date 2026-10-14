# Passwords and encryption

**Status:** accepted · **Depends on:** [main](main.md), [api](api.md), [batch](batch.md) · **Decisions:** [Scope of password-based PDF decryption](https://github.com/Bezoar/pdf2epub/issues/3), [Password and decryption UX](https://github.com/Bezoar/pdf2epub/issues/8), [Core API shape for front ends](https://github.com/Bezoar/pdf2epub/issues/10), [MIT-compatible PDF library stack](https://github.com/Bezoar/pdf2epub/issues/2), [ADR 0001](../adr/0001-python-core.md)

This spec owns how pdf2epub classifies an encrypted input and opens a **password-protected PDF** with a password the user legitimately holds. It covers:

- which encryption it handles and which it refuses;
- where **candidate passwords** come from and in what order they are tried;
- how **permission restrictions** are honoured;
- when the user is prompted;
- how secrets are kept out of every output.

The legal boundary this spec implements is stated in full in [Legal scope](main.md#legal-scope). pdf2epub never circumvents DRM or copy controls. The contract types used here (`PasswordProvider`, `Candidate`, `Secret`, the `password_required` and `password_request` events, and the issue registry) are owned by [api](api.md). How a front end gathers raw passwords (flags, environment, terminal) is owned by [cli](cli.md).

## 1. Scope of decryption

<a id="pwd-r1"></a>**PWD-R1**: pdf2epub shall decrypt only PDFs that use the PDF **Standard security handler** (`/Encrypt` dictionary with `/Filter /Standard`), revisions R2 to R6, with RC4 (40–128 bit), AES-128 or AES-256. Either the **user password** or the **owner password** opens such a file.

<a id="pwd-r2"></a>**PWD-R2**: pdf2epub shall detect an `/Encrypt` dictionary whose `/Filter` is anything other than `/Standard` **before any password is tried**, and shall refuse that conversion with [`drm_protected`](api.md#code-drm_protected). This includes:

- public-key `Adobe.PubSec`;
- Adobe ADEPT `EBX_HANDLER`;
- FileOpen `FOPN_*`;
- any rights-management server handler.

The `/Encrypt` dictionary is never itself encrypted, so detection needs no password.

<a id="pwd-r3"></a>**PWD-R3**: pdf2epub shall recognise the DRM wrapper formats below when such a file is given as an input. It shall report them as [`drm_protected`](api.md#code-drm_protected), not [`not_a_pdf`](api.md#code-not_a_pdf):

- Readium LCP: a ZIP archive containing `META-INF/license.lcpl`, typically `.lcpdf`;
- Adobe `.acsm`: an XML fulfilment token.

<a id="pwd-r4"></a>**PWD-R4**: A Standard-handler file whose revision, algorithm or crypt-filter configuration the PDF library cannot decrypt shall be refused with [`unsupported_encryption`](api.md#code-unsupported_encryption), without trying any password.

<a id="pwd-r5"></a>**PWD-R5**: No code path, option or roadmap item shall bypass a non-Standard handler, ignore permission restrictions, or override [PWD-R2](#pwd-r2), [PWD-R3](#pwd-r3) or [PWD-R10](#pwd-r10). There is no "force" or "ignore restrictions" option.

## 2. Classifying an encrypted file

<a id="pwd-r6"></a>**PWD-R6**: For each input, the core shall classify access in this order and stop at the first step that decides it:

1. Not encrypted → open normally; no password-related issue.
2. Non-Standard handler or DRM wrapper → [`drm_protected`](api.md#code-drm_protected) (PWD-R2, PWD-R3).
3. Unsupported Standard configuration → [`unsupported_encryption`](api.md#code-unsupported_encryption) (PWD-R4).
4. Try the **empty password**. This is always tried first and doesn't count towards the cap in [PWD-R13](#pwd-r13).
5. If the empty password doesn't open the file, try the candidate passwords in the trial order of [PWD-R12](#pwd-r12), stopping at the first that opens it. If the file opens with copy/extract forbidden (by the empty password or a candidate), don't stop there: the remaining candidates are tried as the owner password, as [PWD-R11](#pwd-r11) says.
6. If the file is now open, apply the restriction rules in [§4](#4-permission-restrictions).

<a id="pwd-r7"></a>**PWD-R7**: If no candidate opens the file, the conversion fails with an error issue:

- [`missing_password`](api.md#code-missing_password) when no candidate besides the empty password existed for that file, and no prompt answer was given;
- [`wrong_password`](api.md#code-wrong_password) when at least one supplied or prompted candidate was tried and none worked.

<a id="pwd-r8"></a>**PWD-R8**: A [`wrong_password`](api.md#code-wrong_password) issue shall name the **password sources** tried, as their labels ([PWD-R16](#pwd-r16)), in trial order. It shall never name the passwords themselves.

<a id="pwd-r9"></a>**PWD-R9**: The library calls used to open the file shall be able to tell an owner-password match from a user-password match. pypdf's `decrypt()` returns a `PasswordType`, which is why pypdf (BSD-3-Clause) is a runtime dependency. If the library cannot tell them apart for a file, the match counts as a user-password match; a file with copy/extract forbidden then stays [`restricted`](api.md#code-restricted) unless another candidate is recognised as the owner password (fail closed).

## 3. Outcomes of classification (summary)

| Situation | Issue | Severity | EPUB written |
|---|---|---|---|
| Non-Standard handler, LCP or ACSM wrapper | [`drm_protected`](api.md#code-drm_protected) | error | no |
| Standard handler the library can't decrypt | [`unsupported_encryption`](api.md#code-unsupported_encryption) | error | no |
| No password supplied and the empty password fails | [`missing_password`](api.md#code-missing_password) | error | no |
| Supplied passwords all fail | [`wrong_password`](api.md#code-wrong_password) | error | no |
| Opens, copy/extract forbidden, no owner password | [`restricted`](api.md#code-restricted) | error | no |
| Opens, copy/extract forbidden, owner password supplied | [`owner_password_used`](api.md#code-owner_password_used) | info | yes |
| Opens, extraction permitted | — | — | yes |

## 4. Permission restrictions

<a id="pwd-r10"></a>**PWD-R10**: When a file opens with the empty password or a user password, and its `/P` permissions don't allow copying or extracting text and graphics (bit 5 clear), the core shall honour that restriction. It shall convert only if an owner password is supplied.

<a id="pwd-r11"></a>**PWD-R11**: In that case the core shall go on through the remaining candidates in trial order, prompt included, testing each one as the **owner password**:

- If one matches, the conversion proceeds. It carries an [`owner_password_used`](api.md#code-owner_password_used) info issue whose message is "converted using owner password from `<source label>`".
- If none matches, the conversion fails with [`restricted`](api.md#code-restricted) and no EPUB is written.

The issue is emitted only when the owner password lifted a restriction. If the file has no restrictions, opening it with the owner password produces no issue.

## 5. Password sources and trial order

<a id="pwd-r12"></a>**PWD-R12**: For each encrypted file, candidates shall be tried in this order. The empty password ([PWD-R6](#pwd-r6), step 4) always comes before all of them.

1. **Password map** entries: first an entry whose key is that exact path, then every glob entry that matches, in file order.
2. **Command-line values**, in the order given.
3. The **environment** value.
4. **Password file** lines, top to bottom.
5. The **prompt**, if one is available ([§6](#6-prompting)).

A value that repeats an earlier candidate for the same file is tried once. It keeps the earlier candidate's source label.

<a id="pwd-r13"></a>**PWD-R13**: At most **25** candidates from sources 1–4 may apply to any one file. This cap stops pdf2epub from ever acting as a password guesser (see [Legal scope](main.md#legal-scope)). The core shall check the cap in the run's **preflight** ([API-R29](api.md#api-r29)), before any event is emitted. If any file would exceed it, the run is a usage error: exit code 2 ([batch](batch.md)), and no conversion starts. Prompt attempts ([PWD-R19](#pwd-r19)) don't count towards the cap.

<a id="pwd-r14"></a>**PWD-R14**: The password map is a TOML file. Each key is a path or glob, resolved relative to the folder that holds the map file. Each value is one password string or a list of them, for example:

```toml
"Smith - Thesis.pdf" = "hunter2"
"statements/*.pdf" = ["2024pw", "2025pw"]
```

A map that can't be read, isn't valid TOML, or holds a value that isn't a string or a list of strings is a usage error (exit 2).

<a id="pwd-r15"></a>**PWD-R15**: The password file is UTF-8 text with one candidate per line, tried against every encrypted input. Blank lines are skipped. Each line is the password exactly as written, apart from its line ending. A password file that can't be read is a usage error (exit 2).

<a id="pwd-r16"></a>**PWD-R16**: Every candidate shall carry a **source label**, and only that label may appear in any output:

| Source | Label |
|---|---|
| Password map entry | `map:"<key as written>"` |
| Command-line value N (1-based) | `cli #N` |
| Environment | `env` |
| Password file line N (1-based) | `file:line N` |
| Prompt | `prompt` |

<a id="pwd-r17"></a>**PWD-R17**: When the password map or password file can be read by group or others, pdf2epub shall log a warning to stderr, ssh-style, naming the file and suggesting `chmod 600`. It then continues normally.

<a id="pwd-r18"></a>**PWD-R18**: The core shall provide a `SourcePasswordProvider` built from `PasswordSources(map_file, values, env_value, password_file, prompt)`, so that the trial order, labels, de-duplication and cap all live in the core:

- `map_file`: path or none.
- `values`: command-line secrets, in order.
- `env_value`: one secret or none.
- `password_file`: path or none.
- `prompt`: an optional prompt function `(path, attempt) -> Secret | None`.

It implements the [`PasswordProvider`](api.md) protocol: its `prompt` attribute is `PasswordSources.prompt` (`None` when unset). A front end only gathers the raw sources; it never orders or filters them.

## 6. Prompting

<a id="pwd-r19"></a>**PWD-R19**: A prompt is available for a conversion only when the provider has a `prompt` function. A front end supplies one in these cases (presentation in [cli](cli.md)):

- a **single conversion** run in a terminal, not in `--json` mode;
- a batch run with `ask_password` (`--ask-password`);
- `--json --interactive`, where each prompt becomes a `password_request` event answered on stdin.

Each prompt allows up to **3 attempts** for a file. Typing is not echoed.

<a id="pwd-r20"></a>**PWD-R20**: A blank answer (`None`) skips the file, and three failed attempts end prompting for it. The conversion then fails with:
- [`restricted`](api.md#code-restricted) when the file was already open and an **owner** password was being sought ([PWD-R11](#pwd-r11)), whether the user skipped or failed three times;
- otherwise [`missing_password`](api.md#code-missing_password) on a skip when no candidate had been tried, or [`wrong_password`](api.md#code-wrong_password) when supplied or prompted candidates had been tried.

<a id="pwd-r21"></a>**PWD-R21**: In a batch, the core shall **defer** every conversion that needs a prompt until all conversions that need none have finished. Deferred conversions are prompted in input order. The batch report still lists conversions in input order ([api](api.md)).

<a id="pwd-r22"></a>**PWD-R22**: When no prompt is available and a password would let the conversion go ahead (missing, wrong or owner needed), the core shall emit `password_required` with `sources_tried` (labels only). It then finishes that conversion with the matching issue and goes on to the next. A GUI collects passwords and reruns; finished EPUBs are then skipped ([batch](batch.md)).

## 7. Secret hygiene

<a id="pwd-r23"></a>**PWD-R23**: Password values shall never appear in any of these:

- log output at any verbosity, including `--debug`;
- the human report;
- the `--report` file;
- any JSON event;
- exception text;
- crash output, including an `internal_error` raised from inside a worker.

Candidate values are carried only as [`Secret`](api.md), which is enforced by type.

<a id="pwd-r24"></a>**PWD-R24**: Reports and events shall record only source labels ([PWD-R16](#pwd-r16)). `ConversionResult.password_source` is the label of the candidate that opened the file, or that lifted its restrictions when an owner password was used. It is `null` when no password was needed beyond the empty one.

<a id="pwd-r25"></a>**PWD-R25**: Password environment variables (`PDF2EPUB_PASSWORD`) shall be removed from the environment of every child process, including conversion workers and the OCR engine. Passwords reach a worker only over its pipe ([batch](batch.md)).

<a id="pwd-r26"></a>**PWD-R26**: pdf2epub shall write no secret material to disk (no password value, password hash, decryption key or password cache) and shall cache nothing between runs. Source labels are not secret material: they appear in reports and events as [PWD-R24](#pwd-r24) requires. This rule governs what pdf2epub writes when it runs. Published test passwords of public test fixtures are not user secrets ([testing](testing.md#tst-r9)). The decrypted book content written into the EPUB is the requested output and is not secret material.

## 8. Output

<a id="pwd-r27"></a>**PWD-R27**: The EPUB shall always be written unencrypted. Nothing pdf2epub adds to it (package metadata, navigation, container files, and the elements and attributes it generates) shall contain a password, a password source or the PDF's permission flags. Book text copied from the PDF is reproduced as it is, even if it happens to contain such strings. Protecting the output is the user's responsibility, and the README says so ([main](main.md)).

## 9. Issue messages

<a id="pwd-r28"></a>**PWD-R28**: Access issues shall carry these hints:

| Code | Hint |
|---|---|
| [`missing_password`](api.md#code-missing_password) | "supply the password for this file" |
| [`wrong_password`](api.md#code-wrong_password) | "check the password; sources tried: `<labels>`" |
| [`restricted`](api.md#code-restricted) | "supply the owner password" |
| [`drm_protected`](api.md#code-drm_protected) | "open it in the vendor's reader; pdf2epub will not bypass DRM" |
| [`unsupported_encryption`](api.md#code-unsupported_encryption) | "this PDF's encryption is not supported" |

Front ends may add the flag or setting names that apply to them.

## 10. Acceptance criteria

The fixtures are defined in [testing](testing.md). `CANARY` is a password value unique to the test, e.g. `pw-CANARY-7f3a`.

<a id="pwd-ac1"></a>**PWD-AC1** (covers [PWD-R1](#pwd-r1), [PWD-R6](#pwd-r6), [PWD-R12](#pwd-r12), [PWD-R24](#pwd-r24)):

- **Given** the AES-256 user-password fixture and a provider whose only candidate is its password, from the environment;
- **when** the batch runs;
- **then** the outcome is `converted`, an EPUB is written, and `password_source` is `"env"`.

The same holds for the RC4 and AES-128 fixtures.

<a id="pwd-ac2"></a>**PWD-AC2** (covers [PWD-R7](#pwd-r7)):

- **Given** the AES-256 user-password fixture and no candidates or prompt;
- **when** the batch runs;
- **then** the outcome is `failed`, with one `missing_password` error issue, and no EPUB is written.

<a id="pwd-ac3"></a>**PWD-AC3** (covers [PWD-R7](#pwd-r7), [PWD-R8](#pwd-r8), [PWD-R16](#pwd-r16)):

- **Given** the AES-256 user-password fixture, `values = ["nope"]` and a password file whose line 1 is `alsonope`;
- **when** the batch runs;
- **then** the outcome is `failed` with `wrong_password`, its message names `cli #1` and `file:line 1` in that order, and no EPUB is written.

<a id="pwd-ac4"></a>**PWD-AC4** (covers [PWD-R2](#pwd-r2), [PWD-R5](#pwd-r5)):

- **Given** a fixture whose `/Encrypt /Filter` is `/EBX_HANDLER`, and a provider whose `candidates()` records every call;
- **when** the batch runs;
- **then** the outcome is `failed` with `drm_protected` (hint per [PWD-R28](#pwd-r28)), `candidates()` is never called, and no EPUB is written.

The same holds for `/Adobe.PubSec` and `/FOPN_foweb`.

<a id="pwd-ac5"></a>**PWD-AC5** (covers [PWD-R3](#pwd-r3)):

- **Given** an explicitly named ZIP containing `META-INF/license.lcpl`, and an explicitly named `.acsm` token file;
- **when** the batch runs;
- **then** each is `failed` with `drm_protected`, not `not_a_pdf`.

<a id="pwd-ac6"></a>**PWD-AC6** (covers [PWD-R4](#pwd-r4)):

- **Given** a Standard-handler fixture with a crypt filter the library can't decrypt (e.g. `/V 4` with an unknown `/CFM`), and one candidate;
- **when** the batch runs;
- **then** the outcome is `failed` with `unsupported_encryption`, and the candidate is never tried.

<a id="pwd-ac7"></a>**PWD-AC7** (covers [PWD-R10](#pwd-r10), [PWD-R11](#pwd-r11)):

- **Given** the owner-only fixture (opens with the empty password, copy/extract forbidden) and no candidates;
- **when** the batch runs;
- **then** the outcome is `failed` with `restricted` (hint "supply the owner password"), and no EPUB is written.

<a id="pwd-ac8"></a>**PWD-AC8** (covers [PWD-R9](#pwd-r9), [PWD-R11](#pwd-r11), [PWD-R24](#pwd-r24)):

- **Given** the owner-only fixture and a password map whose matching entry holds `["wrong", "<owner password>"]`;
- **when** the batch runs;
- **then** the outcome is `converted`, with one `owner_password_used` info issue whose message names `map:"<key>"`, and `password_source` is that label.

<a id="pwd-ac9"></a>**PWD-AC9** (covers [PWD-R11](#pwd-r11)):

- **Given** a fixture with user password `u` and owner password `o`, copy/extract forbidden, and `values = ["u"]` only;
- **when** the batch runs;
- **then** the outcome is `failed` with `restricted`.

With `values = ["u", "o"]`, it is `converted` with `owner_password_used` naming `cli #2`.

<a id="pwd-ac10"></a>**PWD-AC10** (covers [PWD-R12](#pwd-r12), [PWD-R14](#pwd-r14)):

- **Given** a provider whose `prompt` records calls, with these sources:
  - a password map with the glob `"*.pdf" = "g"` before the exact key `"a.pdf" = "x"`;
  - `values = ["v"]`;
  - `env_value = "e"`;
  - a password file whose lines are `f1` and `f2`;
- **when** `candidates("a.pdf")` is called;
- **then** the labels come back in the order `map:"a.pdf"`, `map:"*.pdf"`, `cli #1`, `env`, `file:line 1`, `file:line 2`.

<a id="pwd-ac11"></a>**PWD-AC11** (covers [PWD-R12](#pwd-r12)):

- **Given** `values = ["same"]` and `env_value = "same"`;
- **when** `candidates()` is called;
- **then** it returns one candidate, labelled `cli #1`.

<a id="pwd-ac12"></a>**PWD-AC12** (covers [PWD-R13](#pwd-r13)):

- **Given** a password file with 26 distinct non-blank lines and two inputs;
- **when** the CLI runs;
- **then** it exits with code 2, a usage message names the cap of 25, and no `conversion_started` event or EPUB is produced.

<a id="pwd-ac13"></a>**PWD-AC13** (covers [PWD-R14](#pwd-r14), [PWD-R15](#pwd-r15)):

- **Given** a password map that isn't valid TOML, or a password map value of `42`, or a password file that doesn't exist;
- **when** the CLI runs;
- **then** it exits with code 2 before any conversion starts.

<a id="pwd-ac14"></a>**PWD-AC14** (covers [PWD-R17](#pwd-r17)):

- **Given** a password file with mode `0644` holding the correct password;
- **when** the CLI runs;
- **then** stderr contains a warning naming that file and `chmod 600`, and the conversion is `converted`.

With mode `0600`, no such warning appears.

<a id="pwd-ac15"></a>**PWD-AC15** (covers [PWD-R18](#pwd-r18)):

- **Given** a `SourcePasswordProvider` built from `PasswordSources` that hold one value per source;
- **when** it is passed to `run_batch`;
- **then** the trial order, labels and cap behave exactly as in PWD-AC10 to PWD-AC12, without the front end ordering anything.

<a id="pwd-ac16"></a>**PWD-AC16** (covers [PWD-R19](#pwd-r19), [PWD-R20](#pwd-r20)):

- **Given** the AES-256 user-password fixture and a `prompt` that returns a wrong secret three times;
- **when** the batch runs;
- **then** `prompt` is called with attempts 1, 2 and 3, and the outcome is `failed` with `wrong_password` whose sources tried include `prompt`.

If `prompt` returns `None` on attempt 1 instead, `prompt` is called once and the outcome is `failed` with `missing_password`. **And given** the owner-only fixture with copy/extract forbidden and a `prompt` that returns `None`, the outcome is `failed` with `restricted`, not `wrong_password`.

<a id="pwd-ac17"></a>**PWD-AC17** (covers [PWD-R21](#pwd-r21)):

- **Given** a batch `[enc.pdf, plain1.pdf, plain2.pdf]`, where only `enc.pdf` needs a password, and a `prompt` that records the order of events when it is called;
- **when** the batch runs;
- **then** `prompt` is first called after `conversion_finished` for both `plain1` and `plain2`, and `batch_finished.conversions` lists `enc, plain1, plain2` in that order.

<a id="pwd-ac18"></a>**PWD-AC18** (covers [PWD-R22](#pwd-r22)):

- **Given** the AES-256 user-password fixture, `values = ["nope"]` and no `prompt`;
- **when** the batch runs;
- **then** a `password_required` event with `sources_tried == ["cli #1"]` is emitted before that conversion's `conversion_finished`, the outcome is `failed` with `wrong_password`, and the next conversion still runs.

<a id="pwd-ac19"></a>**PWD-AC19** (covers [PWD-R23](#pwd-r23), [PWD-R24](#pwd-r24)):

- **Given** a batch of the AES-256 user-password fixture (correct password `CANARY` from the password map) and a second encrypted fixture where `CANARY` is wrong;
- **when** the CLI runs with `--debug --json --report r.json`;
- **then** `CANARY` appears nowhere in stdout, stderr or `r.json`, while the source label `map:"<key>"` does appear.

<a id="pwd-ac20"></a>**PWD-AC20** (covers [PWD-R23](#pwd-r23)):

- **Given** a worker forced to crash while it holds `CANARY` (test hook), with isolation `subprocess`;
- **when** the batch runs;
- **then** the conversion is `failed` with `internal_error`, and `CANARY` appears nowhere in the issue message, stderr or the report.

<a id="pwd-ac21"></a>**PWD-AC21** (covers [PWD-R25](#pwd-r25)):

- **Given** `PDF2EPUB_PASSWORD=CANARY` in the environment, a scanned encrypted fixture, and `--tesseract` pointing to a stub that writes its environment and argv to a file;
- **when** the CLI runs;
- **then** neither the stub's environment nor its argv contains `CANARY` or `PDF2EPUB_PASSWORD`.

The same holds for the worker process's environment and argv.

<a id="pwd-ac22"></a>**PWD-AC22** (covers [PWD-R26](#pwd-r26), [PWD-R27](#pwd-r27)):

- **Given** the AES-256 user-password fixture converted with password `CANARY`;
- **when** the EPUB and every file created during the run (in the output folder, the temp folder and the user's home cache folders) are searched;
- **then**:
  - the EPUB has no `META-INF/encryption.xml` and opens without a password;
  - neither `CANARY`, the source label nor any permission-flag value appears in any of them;
  - no new file outside the output EPUB remains after the run.

<a id="pwd-ac23"></a>**PWD-AC23** (covers [PWD-R28](#pwd-r28)):

- **Given** batches producing each access issue;
- **when** they finish;
- **then** each issue's `hint` equals the text in the [PWD-R28](#pwd-r28) table, with `<labels>` filled in.

## Open points

The owner accepted points OP18–OP24 in [#51](https://github.com/Bezoar/pdf2epub/issues/51) on 2026-10-14 (numbered as in that review).

- **OP18** **Cap counting ([PWD-R13](#pwd-r13)):** I assumed the empty password and prompt attempts don't count towards the 25-candidate cap, and that duplicates are counted once, after de-duplication.
- **OP19** **Prompt skipped after failures ([PWD-R20](#pwd-r20)):** if supplied candidates failed and the user then skips the prompt, I assumed `wrong_password` rather than `missing_password`. It names the sources tried, which is more useful.
- **OP20** **`password_required` for owner passwords ([PWD-R22](#pwd-r22)):** I assumed the event is also emitted when only an owner password is missing (`restricted`), so a GUI can ask for it.
- **OP21** **DRM wrappers ([PWD-R3](#pwd-r3)):** I assumed `.lcpdf` and `.acsm` files are recognised only when named explicitly or listed with `--files-from`. Folder scans pick only `*.pdf` ([batch](batch.md)), so wrappers in a folder are silently not picked up.
- **OP22** **Owner/user indistinguishable ([PWD-R9](#pwd-r9)):** I assumed a match counts as a user-password match when the library can't tell, so a restricted file fails closed with `restricted` (the same behaviour PWD-R9 states).
- **OP23** **Readable-file warning ([PWD-R17](#pwd-r17)):** I assumed it is a stderr log line, not an issue, because it isn't tied to a conversion.
- **OP24** **Hint wording ([PWD-R28](#pwd-r28)):** the hints for `missing_password`, `wrong_password` and `unsupported_encryption` are my wording. Only the `restricted` and `drm_protected` hints were decided.
