# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

A LangGraph agent that crawls workatastartup.com (YC) for fresher or intern-level roles. A local Ollama LLM extracts and scores each listing, and the results are exported to a local Excel sheet that the user reviews by hand. **No auto-apply. That feature is out of scope.**

Ranking priorities, in order: remote/WFH, high pay, non-DSA interview process, then no or internship-only experience required.

Status: planning phase. No code yet. Update this file once the stack and commands exist.

## Hard rules

- **Never** add Claude as co-author and never mention Claude or AI in commits, PRs, README or code. The user is the sole author.
- Make small, frequent commits and push each one to `origin main`.
- **The LLM host is off-limits for inference until the user says go.** The lab PC (`amaloch@100.104.107.17` over Tailscale, RTX 2000 Ada 16 GB) runs other heavy GPU jobs. Do not pull, load or run models there and do not run tests that hit Ollama. Build the harness only.
- The model must stay swappable through config (an Ollama model tag). Don't hard-code model-specific behavior outside the LLM adapter layer.
