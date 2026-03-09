# YouTube Learning Tree

A fast, lightweight web app for creating personal YouTube recommendation trees.

## Features
- Up to 10 active trees (create, copy, archive/unarchive, delete)
- Unlimited node growth per tree
- Node color changes by decision (`liked` / `disliked` / pending)
- Mandatory 3–5 feedback points per video, each with a binary positive/negative toggle
- Persistent SQLite database
- Retro, cozy, responsive UI
- Recommendation engine based on the popular **Rocchio relevance feedback algorithm** over a computer-science word bank

## Run

```bash
python3 app.py
```

Open http://localhost:3000
