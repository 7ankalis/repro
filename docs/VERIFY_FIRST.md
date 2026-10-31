# Verify first (gate G0) — kill every unknown before building on it

Do these yourself (or with one agent), in order. Write the answers into `docs/HANDOFF.md`.
If any check fails, the fallback is listed — decide immediately, don't drift.

## 1. Meta Model API (15 min)
```
cp .env.example .env    # put MODEL_API_KEY
make install && repro doctor
```
- [ ] `muse-spark-1.3` answers via `https://api.meta.ai/v1/chat/completions`.
- [ ] Tool calling returns `tool_calls` (doctor prints ✓).
- [ ] `response_format: json_schema` accepted? (run `repro factcheck datasets/demo/slop_curl_01` after step 3).
      If rejected, `llm.structured()` already falls back to instructions + repair — just confirm it works.
- [ ] Note the price per 1M tokens → `REPRO_PRICE_IN/OUT` in `.env` (so eval cost numbers are real).
- [ ] Rate limits: note RPM/TPM. If tight, keep `max_agent_steps` ≤ 15.
- Fallback: none needed — the API is OpenAI-compatible; any issue is config.

## 2. Docker + disk (10 min)
- [ ] `docker info` works without sudo. **Free disk ≥ 40 GB** (ARVO images are 1–5 GB each).
- [ ] Your machine: ≥ 4 cores, ≥ 16 GB RAM ideal. If weaker: Modal sandboxes / a cloud VM (Modal credits).

## 3. ARVO (45 min) — the biggest unknown
```
docker pull n132/arvo:42487096-vul      # example id from the ARVO README; pick your own later
docker run --rm -it n132/arvo:42487096-vul arvo           # expect an ASan/UBSan report
docker run --rm --entrypoint sh n132/arvo:42487096-vul -c 'cat $(which arvo)'   # HOW it reproduces
```
Record in HANDOFF.md:
- [ ] Where the **PoC file** lives (path in the arvo script) and which **fuzz target** binary runs it (`/out/...`).
- [ ] Where the **source** lives (`/src/<project>`) → `src_dir`.
- [ ] Does `arvo compile` work offline (`--network none`)? How long does it take?
- [ ] Does the image start with `--entrypoint /bin/sh -c "sleep infinity"` (what `Sandbox.start` does)?
- [ ] Save the output of `arvo` to a file and run `repro sanitize that.log` → parser must extract type + frames.
      If not, add the log to `tests/` as a new case (task B1).
- Fallback if ARVO images are unusable: build 3–5 small targets yourself from OSS-Fuzz `projects/<name>/`
  (`python infra/helper.py build_fuzzers --sanitizer address <name>`), or curl with known historical CVEs at old tags.

## 4. curl ASan image (runs in background, 10 min of your time)
```
make curl-image     # docker/curl-asan.Dockerfile
docker run --rm repro/curl-asan:latest src/curl --version
```
- [ ] Builds. (If `--with-openssl` fails, try `--without-ssl` — slop reports don't need TLS.)

## 5. Real curl slop reports (30 min, can be parallel)
- [ ] Find Daniel Stenberg's public list of AI-slop reports to curl (his blog and a public gist/HackerOne disclosed
      reports). Collect 5–10 report texts with their dates → task C4.
- These are public, disclosed reports. Use them only as evaluation input; credit the source in the README.

## 6. Muse Code (10 min, optional)
- [ ] Can it run headless (CLI) inside a container with `MODEL_API_KEY`? If yes → stretch task D6. If no → just use
      it to build the project and say so in the README/video.

## Exit criteria = gate G0
`repro doctor` all ✓ · one ARVO crash parsed by `repro sanitize` · curl image building · HANDOFF.md has the answers.
