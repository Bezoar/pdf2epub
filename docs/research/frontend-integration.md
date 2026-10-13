# Research: front-end integration patterns for the core

Ticket: [#4](https://github.com/Bezoar/pdf2epub/issues/4) · Status: research
note, 2026-10-13 · Feeds: #7 (implementation language and packaging), #10
(core API shape for front ends), #8 (password UX), #9 (batch semantics).

## Question

How should the pdf2epub core be exposed so that later front ends can drive it?
The first front end is a native macOS app, possibly a separate implementation.
This note compares four integration styles:

1. an in-process library API,
2. a subprocess CLI that emits a JSON-lines event stream,
3. a local server or IPC (XPC, gRPC, HTTP),
4. a C ABI / FFI.

For each one it covers progress, cancellation, password prompts in the middle
of a batch, the error model, macOS packaging, sandbox and notarization, and
what the choice implies for the core language (Python, Rust or Swift).

The archived prior spec (`SPEC.md` §4.2) chose "Python library + thin CLI
wrapper". That spec's `convert(...) -> result` call has no hook for progress,
cancellation or interactive passwords. Every option below needs those hooks
somewhere.

## TL;DR

- **Design the core around three seams, whatever the language:**
  1. an **event sink**: progress, warnings, per-file results, all plain
     serialisable data;
  2. a **cancellation token** that the core checks cooperatively;
  3. a **password provider**, either a callback or "defer and report".
- **Ship a machine-readable CLI mode in v1:** JSON Lines on stdout, logs on
  stderr, with a schema version and a final summary record. The JSON mode
  should also be able to read requests (passwords, cancel) as JSON Lines on
  stdin.
- This CLI mode is the cheapest macOS integration. A Swift app embeds the CLI
  as a sandbox-inheriting helper tool and drives it with `Process`, and the
  same protocol also serves a later XPC wrapper or other GUIs.
- In-process or FFI bindings can come later. They only pay off if the core is
  Rust (UniFFI generates Swift bindings) or if the GUI is itself Python.

## Background facts (macOS)

- **Notarization** (required for Developer ID distribution since macOS 10.15)
  requires:
  - every executable code-signed with a Developer ID certificate;
  - the Hardened Runtime enabled "for your app and command line targets";
  - a secure timestamp;
  - no `get-task-allow` entitlement.

  Source: [Notarizing macOS software before distribution](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution).
  Mac App Store apps don't need separate notarization (same source).
- **Hardened Runtime** disallows capabilities such as JIT unless you add an
  exception entitlement. "Shared libraries, frameworks, and in-process plug-ins
  inherit the entitlements of their host executable."
  Source: [Hardened Runtime](https://developer.apple.com/documentation/security/hardened-runtime).
- **The Mac App Store requires App Sandbox.** Apps "must be appropriately
  sandboxed" (Guideline 2.4.5(i)) and "should be self-contained in their
  bundles" and may not download or execute code that changes functionality
  (2.5.2).
  Source: [App Review Guidelines](https://developer.apple.com/app-store/review/guidelines/).
- **An embedded command-line tool must inherit the app's sandbox.**
  - Apple: "If your macOS app embeds a command-line tool, that tool must
    inherit the containing app's sandbox configuration"
    ([Protecting user data with App Sandbox](https://developer.apple.com/documentation/security/protecting-user-data-with-app-sandbox)).
  - The tool is signed with exactly `com.apple.security.app-sandbox` +
    `com.apple.security.inherit`. "Adding other entitlements to the tool can
    cause problems." `get-task-allow` is incompatible with `inherit`, so the
    sandboxed tool can't be debugged in place. An externally built tool (e.g.
    `make`, or by extension `cargo`/PyInstaller) is ad-hoc signed with those
    entitlements, then added to the app's "Embed Helper Tools" phase and
    re-signed by Xcode.
    Source: [Embedding a command-line tool in a sandboxed app](https://developer.apple.com/documentation/xcode/embedding-a-helper-tool-in-a-sandboxed-app).
  - The page says the same process works for Developer ID (non-App-Store)
    distribution.
- **Bundle layout rules.**
  - Helper executables go in `Contents/MacOS`, dylibs in
    `Contents/Frameworks`, and data in `Contents/Resources`.
  - A bundle is read-only. Apple uses Python as its example: writing `.pyc`
    files next to sources "breaks the seal on your app's code signature".
    Point such runtimes at a writable location instead.

  Source: [Embedding nonstandard code structures in a bundle](https://developer.apple.com/documentation/xcode/embedding-nonstandard-code-structures-in-a-bundle).
- **File access in the sandbox.**
  - Open/save panels and drags onto the Dock icon extend the app's sandbox to
    the chosen URLs. Chosen folders are covered recursively.
  - Access can be handed to another process (e.g. an XPC service) by passing
    a URL bookmark created with no options.

  Source: [Accessing files from the macOS App Sandbox](https://developer.apple.com/documentation/security/accessing-files-from-the-macos-app-sandbox).
- **XPC services.**
  - Each XPC service lives in `Contents/XPCServices` and "has its own
    sandbox".
  - `launchd` launches services on demand, restarts them after a crash and
    kills them with `SIGKILL` when idle, so a service "should be completely
    stateless".
  - If a service crashes mid-request, the client sees the connection
    invalidated.
  - Apple notes that `NSTask`/`posix_spawn` children cannot get their own
    sandbox, which XPC can.

  Sources: [Creating XPC Services (archive)](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingXPCServices.html),
  [Creating XPC services](https://developer.apple.com/documentation/xpc/creating-xpc-services)
  (modern Swift `XPCListener`/`XPCSession` with `Codable` messages).
- **Stopping a `Process`.** `Process.interrupt()` sends `SIGINT`. "It isn't
  always possible to interrupt the receiver because it might be ignoring the
  interrupt signal."
  Source: [Process.interrupt()](https://developer.apple.com/documentation/foundation/process/interrupt()).
  `terminate()` also exists.
  Source: [Process.terminate()](https://developer.apple.com/documentation/foundation/process/terminate()).
- **Listening sockets need an entitlement.** A sandboxed app needs
  `com.apple.security.network.server` to accept incoming network connections.
  Source: [network.server entitlement](https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.security.network.server).

## Prior art for machine-readable event streams

| Tool | Mechanism | Lessons |
|---|---|---|
| ffmpeg | `-progress URL`. Periodic `key=value` blocks, each ending with `progress=continue` or `progress=end`. The period is set by `-stats_period` (default 0.5 s). E.g. `-progress pipe:1`. ([ffmpeg docs](https://ffmpeg.org/ffmpeg.html)) | Progress goes on a separate channel. A clear terminal marker. Rate-limited updates. |
| cargo | `--message-format=json`: "JSON object per line" on stdout. A `reason` field picks the message type (`compiler-message`, `compiler-artifact`, `build-script-executed`, `build-finished` with `success`). It warns that other tools' output may be mixed in, so read only lines starting with `{`. ([cargo external tools](https://doc.rust-lang.org/cargo/reference/external-tools.html#json-messages)) | Discriminator field. A final "finished" record. Keep stdout pure. |
| ripgrep | `--json` emits JSON Lines with `type` ∈ {begin, match, context, end}. The set "may expand over time". Non-UTF-8 data goes under a `bytes` key instead of `text`. ([grep-printer JSON](https://docs.rs/grep-printer/latest/grep_printer/struct.JSON.html)) | Per-item begin/end envelopes. Forward-extensible types. Lossless handling of odd strings (PDF metadata is often non-UTF-8). |
| git | `--porcelain[=v2]` output "will remain stable across Git versions and regardless of user configuration". v2: "Parsers should ignore headers they don't recognize." ([git-status](https://git-scm.com/docs/git-status)) | Explicit format versioning and a must-ignore-unknown rule. |
| LSP | JSON-RPC over stdio with `Content-Length` framing. `$/cancelRequest`: a cancelled request "still needs to return … a response", ideally with `RequestCancelled`. `$/progress` with `begin`/`report`/`end`, `percentage` 0–100 and `cancellable`. ([LSP 3.17](https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/)) | A proven bidirectional design for progress, cancel and server→client questions over a child process's stdio. |

Format conventions:
- [JSON Lines](https://jsonlines.org/): UTF-8 with no BOM, one JSON value per
  line, terminated by `\n`.
- [JSON-RPC 2.0](https://www.jsonrpc.org/specification): notifications have no
  `id` and get no reply; error objects carry an integer `code`, a `message`
  and optional `data`; the protocol is transport-agnostic.

## Option comparison

### 1. In-process library API

The front end links or imports the core and calls
`convert(..., on_event=, cancel=, password_provider=)`.

- **Progress:** callbacks or an iterator of events. Lowest latency and richest
  types.
- **Cancellation:** must be cooperative (a token checked between pages and
  stages). In Python, signal handlers run only on the main thread, and "a
  long-running calculation implemented purely in C … may run uninterrupted for
  an arbitrary amount of time"
  ([signal docs](https://docs.python.org/3/library/signal.html)). Cancellation
  is therefore only as fine-grained as the core's checkpoints, whatever the
  language.
- **Mid-batch password:** the most natural fit. The core calls
  `password_provider(file)` and the UI shows a sheet. Watch out for threading:
  the callback arrives on a worker thread and must hop to the main/UI thread.
- **Error model:** native exceptions or `Result` values. A single bad file can
  crash the whole UI process unless the core is crash-free (Rust panics and
  native PDF libraries are both risks).
- **macOS packaging:**
  - **Swift core:** trivial.
  - **Python core:** the app must embed CPython by calling `Py_Initialize()`
    from its own `main`
    ([Embedding Python](https://docs.python.org/3/extending/embedding.html)).
    It must also ship and sign every `.so` and keep bytecode out of the bundle
    (Apple's `.pyc` warning above). Python 3.13 added
    `--with-app-store-compliance` to patch stdlib strings that trip App Store
    inspection
    ([configure docs](https://docs.python.org/3/using/configure.html)).
  - **Rust core:** the core links in as a static library or framework via FFI
    (see option 4).
- **Language implications:** only cheap when the front end and the core share
  a language or runtime. A Python core plus a Swift app is the expensive
  combination.

### 2. Subprocess CLI + JSON-lines event stream

The front end spawns `pdf2epub --json ...` and reads events from stdout. Logs
go to stderr.

- **Progress:**
  - Events such as `file_started`, `page_progress {done,total}`, `warning`,
    `file_finished` and `batch_finished`.
  - Rate-limit progress events the way ffmpeg's `-stats_period` does.
  - End with a terminal record, like cargo's `build-finished` or ffmpeg's
    `progress=end`.
- **Cancellation:**
  - `Process.interrupt()` (SIGINT) asks the CLI to stop. The CLI catches it,
    finishes or discards the current file, emits `batch_finished
    {cancelled:true}` and exits.
  - `terminate()` is the hard fallback.
  - For per-file cancel, or cancel without a signal, accept a `{"op":"cancel"}`
    line on stdin. This is the LSP `$/cancelRequest` pattern.
- **Mid-batch password:** two workable designs.
  - **(a) Defer and report.** The CLI emits `password_required {file}`, skips
    that file and keeps going. The GUI collects passwords and starts a second
    run. This needs no stdin protocol.
  - **(b) Interactive.** With `--json --interactive`, the CLI emits
    `{"type":"request","id":7,"kind":"password","file":...}` and reads
    `{"id":7,"password":"..."}` from stdin, as in JSON-RPC. LSP's
    `window/showMessageRequest` is precedent for a server asking its client a
    question.
  - Either way, never pass passwords on argv. Process arguments are visible
    to other local users
    ([CWE-214](https://cwe.mitre.org/data/definitions/214.html)).
- **Error model:**
  - Per-file `file_finished {status, error:{code, message, data}}` with stable
    string codes such as `encrypted`, `drm`, `unreadable` and `internal`,
    following the JSON-RPC error object shape.
  - The process exit code stays the coarse summary (the spec's 0–4 codes).
  - A core crash kills only the child. The GUI shows "conversion failed" and
    stays alive.
- **macOS packaging:**
  - Embed the CLI as a helper tool in `Contents/MacOS`, signed with only
    `app-sandbox` + `inherit`, with the Hardened Runtime on and Developer ID
    plus notarization for direct distribution (sources above).
  - **Python:** freeze it. PyInstaller signs embedded binaries with
    `--codesign-identity`, enables the Hardened Runtime when an identity is
    given, and accepts `--osx-entitlements-file`
    ([PyInstaller macOS notes](https://pyinstaller.org/en/stable/feature-notes.html)).
    Prefer onedir. Onefile unpacks itself to a temporary directory at every
    run ([PyInstaller operating mode](https://pyinstaller.org/en/stable/operating-mode.html)).
    Alternatives:
    - [python-build-standalone](https://github.com/astral-sh/python-build-standalone)
      ("self-contained, portable … Python distributions");
    - [Briefcase](https://briefcase.beeware.org/en/stable/reference/platforms/macOS/index.html),
      which signs and notarizes by default but is aimed at whole apps, and
      whose console apps require `.pkg`.
    - Every bundled `.so`/`.dylib` must be signed. Apple's nonstandard-layout
      guide covers moving them to `Contents/Frameworks` with `@rpath`.
  - **Rust:** one self-contained binary. Ad-hoc sign it with the two
    entitlements, as in Apple's external-tool walkthrough.
  - **Sandbox file access:** the helper inherits the app's sandbox. Whether
    access granted dynamically through open panels carries over to a child
    started afterwards is **not stated** in the pages reviewed. Prototype this
    (open panel → `Process` → helper reads the file) before committing. Two
    fallbacks:
    - make the helper an XPC service and pass bookmarks, which Apple
      documents;
    - pass file descriptors or stdin/stdout data.
- **Language implications:**
  - Works with any core language.
  - The Swift side needs only `Process`, a `Pipe`, a line splitter
    and `JSONDecoder`.
  - The same contract serves future GUIs on other platforms, scripting and
    tests (golden event logs).

### 3. Local server / IPC (XPC, gRPC, HTTP)

- **XPC:**
  - Native to Apple platforms, with `Codable` messages
    ([Creating XPC services](https://developer.apple.com/documentation/xpc/creating-xpc-services)).
  - The service has its own sandbox and crash isolation, and `launchd` manages
    its lifecycle.
  - Bookmarks are the documented way to share file access with it.
  - Progress and passwords need a reverse channel: a client-exported object
    or a message from the service to the client.
  - The service must tolerate being killed when idle (archive guide above).
  - **Language implications:** the listener is written against Apple's
    C/Swift/ObjC XPC APIs. A Python or Rust core would sit behind a small
    Swift XPC shim that either links the core (option 1/4) or spawns the CLI
    (option 2). XPC is therefore a wrapper around another option, not a
    replacement for one.
- **gRPC / HTTP on localhost:**
  - Typed streaming RPCs suit progress well.
  - gRPC cancellation is a signal only. "The gRPC library in general does not
    have a mechanism to interrupt the application-provided server handler."
    Long handlers "must periodically check" whether they've been cancelled
    ([gRPC cancellation](https://grpc.io/docs/guides/cancellation/)).
  - Costs on macOS:
    - a sandboxed listener needs `com.apple.security.network.server` (cited
      above);
    - ports, discovery and local authentication have to be designed;
    - a heavier dependency stack in both processes.
  - Only worth it if a web UI or remote front end becomes a goal.
- **Progress, cancel and password:** all are good, because the protocol is
  bidirectional by construction.
- **Error model:** gRPC status codes or HTTP problem documents.

### 4. C ABI / FFI

The core exports `extern "C"` functions. Generated headers (e.g. via
[cbindgen](https://github.com/mozilla/cbindgen): "creates C/C++11 headers for
Rust libraries which expose a public C API") or a binding generator such as
[UniFFI](https://mozilla.github.io/uniffi-rs/latest/) ("full support for
Kotlin, Swift and Python") expose it to Swift.

- **Progress and password:** callbacks into foreign code.
  - UniFFI calls these foreign traits or callback interfaces. The foreign
    implementation "must be safe to call from multiple threads at once"
    ([callback interfaces](https://mozilla.github.io/uniffi-rs/latest/types/callback_interfaces.html)).
  - Raw C needs function pointers plus a `void*` context.
- **Cancellation:** cooperative only. UniFFI states "We don't directly support
  cancellation … even when the underlying platforms do" and suggests a
  `cancel()` method that sets a flag
  ([UniFFI async](https://mozilla.github.io/uniffi-rs/latest/futures.html)).
  That is exactly the cancellation-token seam recommended here.
- **Error model:**
  - Error enums map to Swift `throws` through UniFFI.
  - In raw C, use error codes plus out-params.
  - Panics must not cross the boundary. A panic reaching a non-`unwind`
    `extern "C"` boundary aborts the process (taking the GUI with it), and
    `catch_unwind` only catches unwinding panics
    ([Rustonomicon FFI](https://doc.rust-lang.org/nomicon/ffi.html)).
- **macOS packaging:**
  - An XCFramework or static lib that Xcode signs with the app.
  - No separate sandbox profile or helper.
  - Smallest footprint.
- **Language implications:**
  - **Rust:** excellent. One core can serve a CLI binary, Swift (UniFFI),
    Python ([PyO3](https://pyo3.rs/), "Rust bindings for Python … creating
    native Python extension modules") and C.
  - **Python:** essentially impossible as the provider. Python is the
    consumer of C ABIs, not a producer, short of embedding the interpreter
    (option 1).
  - **Swift:** a C ABI via `@_cdecl` is possible, but unusual and
    underdocumented.

## Summary matrix

| | In-process lib | CLI + JSONL | XPC / gRPC / HTTP | C ABI / FFI |
|---|---|---|---|---|
| Progress | callbacks, best | events on stdout, good | streams, good | callbacks, good |
| Cancellation | cooperative token | SIGINT / stdin `cancel` → cooperative | RPC cancel → cooperative | cooperative flag |
| Mid-batch password | callback | defer-and-report or stdin request/response | reverse RPC | callback |
| Crash isolation | none | **full** (child process) | full | none |
| Error model | native | per-file error objects + exit code | status codes | enums/codes; panics must be caught |
| macOS cost | Swift: none; Python: embed CPython (heavy) | helper tool, 2 entitlements; Python must be frozen | XPC shim + bookmarks; gRPC/HTTP needs `network.server` | Rust: XCFramework |
| Core language fit | same-language only | **any** | any, but needs a shim | Rust (UniFFI) ≫ Swift ≫ Python |
| Serves other GUIs/scripts | only same language | **yes** | yes | yes, via bindings |

## Implications for the core language (input to #7)

- **Python core.** The CLI + JSONL helper is the only cheap path to a Swift
  app. The costs are freezing the interpreter and signing many `.so` files.
  The in-process route is the expensive one. Note also the PDF-library
  licensing constraint: PyMuPDF/MuPDF is "AGPL and commercial"
  ([PyMuPDF license](https://pymupdf.readthedocs.io/en/latest/about.html)),
  which matters for an MIT project (see #2).
- **Rust core.** It keeps every door open: a single signed helper binary now,
  and UniFFI Swift bindings or an XCFramework later with the same seams. It
  can also expose a Python API via PyO3. Panic discipline at the FFI boundary
  is required.
- **Swift core.** In-process is free for the Mac app, with PDFKit providing
  `unlock(withPassword:)`
  ([PDFKit](https://developer.apple.com/documentation/pdfkit/pdfdocument/unlock(withpassword:)))
  and Vision available for OCR
  ([VNRecognizeTextRequest](https://developer.apple.com/documentation/vision/vnrecognizetextrequest)).
  Those are Apple-platform frameworks, though, so a Swift core weakens the
  cross-platform CLI story. This fits the owner's "separate Swift
  implementation" idea better than "one core for all".

## Recommendation: v1 design so a macOS front end is cheap later

1. **Core API (#10).** Shape it as
   `convert_batch(inputs, options, sink, cancel, passwords) -> BatchResult`:
   - `sink` receives typed, serialisable events with stable `type` names.
   - `cancel` is a token the core checks between pages and between stages.
   - `passwords` is an interface with one method, `get(file, attempt) ->
     password | skip`. The CLI implements it as tty prompt, `--password-file`,
     JSON request or skip. A GUI implements it as a sheet.
   - Keep every event and error a plain data record (no exceptions or objects
     crossing the boundary). Then option 2, an XPC shim and option 4 are pure
     transport adapters.
2. **Ship `--json` in v1 (cheap insurance):**
   - JSON Lines on stdout only, everything human-readable on stderr (avoids
     cargo's mixed-output pitfall).
   - The first record is `{"type":"hello","schema":1,"version":"x.y.z"}`.
     Consumers must ignore unknown types and fields (git porcelain v2,
     ripgrep).
   - Per-file `file_started` / `file_finished`, rate-limited `progress`,
     `warning`, and a terminal `batch_finished` that carries the batch
     report. That record doubles as the spec's `--report` JSON, which ties to
     #9.
   - Errors are `{code, message, data}` with a fixed code vocabulary that
     maps to exit codes.
   - Non-UTF-8 strings go under `bytes` (base64), as ripgrep does.
3. **Passwords (#8).** Default batch behaviour is *defer-and-report*: emit
   `password_required` and continue. Add the stdin request/response mode
   (`--json --interactive`) when the GUI needs it. It is a small, additive
   extension that follows JSON-RPC/LSP shapes. Never accept passwords on argv.
4. **Cancellation contract.**
   - SIGINT means "stop after a checkpoint, emit `batch_finished
     {cancelled:true}`, delete partial outputs, exit with a distinct code".
   - A second SIGINT or SIGTERM means stop immediately.
   - Document how long a checkpoint can take (a single page, or one OCR call).
5. **Packaging hygiene from day one:**
   - The CLI must run from a read-only location.
   - Caches and temp files go to a configurable or OS temp/cache directory,
     never next to the executable.
   - No runtime downloads (OCR models, fonts) for the App Store variant.

   These keep a future sandboxed, notarized helper viable regardless of
   language.
6. **Before building the Mac app**, prototype the sandbox file-access question:
   does a helper spawned with `inherit` see the files from a later open panel?
   If not, wrap the helper in an XPC service and pass bookmarks.

## Open questions

- Sandbox inheritance of dynamically granted file access for helpers (above).
  This needs a 30-minute prototype.
- Whether the Mac App Store is a target at all. If it's Developer ID only, the
  sandbox is optional, though still recommended. Notarization is still
  required.
- Progress units: pages are natural, but OCR pages can be far slower than
  text pages (estimate, not measured). Consider weighted `work_units`.
