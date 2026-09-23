# Resumix

[![build](https://github.com/gcontini/resumix/actions/workflows/ci.yml/badge.svg)](https://github.com/gcontini/resumix/actions/workflows/ci.yml)
[![Codacy Badge](https://app.codacy.com/project/badge/Grade/f4ef6c19a55741d8b3cdf1f210b0ba82)](https://app.codacy.com/gh/gcontini/resumix/dashboard?utm_source=gh&utm_medium=referral&utm_content=&utm_campaign=Badge_grade)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Turn a job description and your unstructured experiences into a tailored, two-page LaTeX CV and a cover letter, using any OpenAI-compatible model.

Produces an honest CV that you can actually defend in a job interview.

<details>
<summary><b>CV Preview</b></summary>

![CV Preview](doc/images/cv.png)

[**See what it produces →** `examples/sample_cv.pdf`](examples/sample_cv.pdf)
</details>

Features:
- **Analyses** the Job Description you select against your profile — match score, salary, seniority, skills, gaps (optional).
- **Writes** an honest CV tailored to the posting, reviewed against your profile for
  invented claims, condensed until it fits two pages, with matching keywords
  highlighted.
- **Renders** real LaTeX to a PDF, and optionally a cover letter.
- It can watch your **clipboard** or a **folder** for  multiple generation, or run **once** on a single file.

You need to provide:
- A list of your work experiences, skills, the more you put the better the CV will be (as long as you can defend it in an interview). You don't have to worry about writing them in a perfect style: `resumix` will fix it for you.
- Some customization data for the cv (your phone, linkedin...)
   - a signature scan - looks good on your cv. 
- The job description
- You api key and model configurations 

## Will it work for me?

It started as my own personal lab to learn AI assisted coding and to pass the ATS with flying colors. It's not tested across different cv formats and sizes. It's sized for a well established professional with >10 
years of experience and 3-8 working experiences. 

It is focused on getting the content of the CV right instead of customization of presentations.

If it doesn't work for you "out of the box" check for options, it is extremely *tunable* but you may need some investment. Ask on the [forum](https://github.com/gcontini/resumix/discussions) for help or open an issue.

It took me a couple of weeks to get it to work well. If you do on your own the points you're going to spend time on are:

* prepare the templates for your cv
* the models will continue exaggerate your experiences and to pass the lenght limits until you put in place a review step.
* the whole review process has to be tuned (temperature=0, retries...) or it will not converge nor find errors.
* the models thinking budgets need to be tuned or they will consume all your token plan with no added benefit.

## Download and run

resumix is two pieces: a server that holds the model keys and the LaTeX
toolchain, and a client executable you run on your machine. Neither needs the
other installed locally — the client talks to the server over HTTP.

**1. Run the server** — a container image, published on Docker Hub:

```bash
docker run -d -p 8080:8080 \
  -e MODEL_API_KEY=... \
  lmstch/resumix:latest
```

Any OpenAI-compatible provider works — see
[`server/README.md`](server/README.md) for the other providers and the full
environment table. `curl localhost:8080/healthz` should report `pdflatex: true`.

**2. Download the client** — a single executable, no Python required, from the
[releases page](https://github.com/gcontini/resumix/releases): pick
`resumix-linux-x86_64` or `resumix-windows-x86_64`, unpack it, and put your
own `candidate_profile.json` and `candidate_data.json` beside it (start from
the fictional set in the download's `examples/candidate/`).

```bash
./resumix --server http://localhost:8080 clipboard --out ~/applications
```

Copy a job posting to your clipboard; resumix checks it, shows you the
analysis, and on confirmation writes the CV into
`~/applications/cv/<day>/<Company>_<Title>/`. `watch` and `submit` work the
same way against files instead of the clipboard —
[`client/README.md`](client/README.md) covers all three modes, configuration,
and the output layout.

## Architecture

Below how the data you provide is merged to create the final CV:

```mermaid
flowchart LR
    CP["candidate_profile.json"] --> LLM["LLM<br/>Model Calls"]
    JD["job_description.txt"] --> LLM
    LLM --> DOC(("+"))
    CD["candidate_data.json"] --> DOC
    DOC -->|"tailored CV data<br/>.json"| JE["template engine"]
    TPL["cv template"] -->|resume.tex.jinja| JE
    RES["cv images"] --> JE
    JE -->|"cv.tex"| LATEX["LaTeX engine"]
    LATEX -->|"cv.pdf"| PDF(["Your CV"])

    classDef data fill:#E3F2FD,stroke:#1565C0,color:#0D47A1;
    classDef code fill:#FFF3E0,stroke:#E65100,color:#7A3E00;
    class CP,JD,CD,TPL,PDF,RES data;
    class LLM,JE,LATEX,DOC code;
```

You can download `"tailored CV data.json"` and `cv.tex` toghether with the final pdf, in case you want to modify something manually and resubmit them for rendering via the client.

Package boundaries, what crosses the wire, and the async job model are in
[doc/architecture.md](doc/architecture.md).

## Development

```bash
uv sync
uv run pytest                   # all four suites; no API key, no network
uv run resumix-api            # the server, from source
uv run resumix --help         # the client, from source
uv run --group docs mkdocs serve  # the documentation site, on :8000
```

Tests that need `pdflatex` skip themselves without it. The engineering rules
the code follows are in [AGENTS.md](AGENTS.md).

## Known limitations

- A CV job cannot be cancelled: an abandoned one holds a slot until its own
  budget runs out. See [PLANNED-FEATURES.md](PLANNED-FEATURES.md).
- A job id only means something to the instance holding its directory, so run
  one instance per `RESUMIX_WORK_DIR`.
- One template, one language. Bring your own `.tex.jinja` if you want a different shape.

## License

MIT — see [LICENSE](LICENSE).
