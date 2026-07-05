# Blind naturalness evaluation (the Delta-4 honesty check)

The automated benchmark measures *mechanics* (latency, takeovers, overlap). Whether Duet
actually *feels* 4+ points better is a human judgment, and we publish whatever number comes
out — including a disappointing one.

## Materials

`eval/bench/out/clips/` contains one WAV per scenario per system: the same simulated caller,
the same SDR persona, the same conversation script — `duet-*.wav` (full-duplex) vs
`cascade-*.wav` (faster-whisper → Gemini → Piper with standard endpointing). Filenames are the
only giveaway, so rename before testing.

## Protocol (minimum viable, ~10 min per rater)

1. Pick 6 scenario pairs. Rename to `A1/B1 … A6/B6`, randomizing which system is A per pair
   (record the key privately).
2. Recruit ≥5 raters who are not the authors. No context beyond: *"You'll hear short calls
   between a customer and an AI sales agent. Rate how natural the agent's conversational
   behavior feels, 1–10. Ignore voice quality/accent; judge timing: response speed,
   interruptions, talking over the customer."* (Voice timbre is a TTS-model property, not
   what Duet changes — raters must be told this or the prettier TTS wins on looks.)
3. Raters listen pair-by-pair (A then B, order shuffled per pair), score both.
4. Delta = mean(duet scores) − mean(cascade scores). Publish mean, per-rater spread, and N
   in the README and DECISIONS.md, whatever the value.

## Status

- [ ] Clips generated (automated — done by `run_bench.py`)
- [ ] Raters recruited (needs the project owner — I can't recruit humans)
- [ ] Delta published in README

Until the human number exists, the README may cite only the mechanical metrics and must say
"human naturalness delta: not yet measured."
