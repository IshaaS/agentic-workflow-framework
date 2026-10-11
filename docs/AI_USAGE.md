# AI-assisted development disclosure

## Overview

I developed this assessment through an AI-assisted engineering process. I interpreted the requirements, directed the architecture and implementation scope, evaluated design trade-offs, tested the running system, and decided what changes were needed before merging. ChatGPT supported planning and review, while Claude Code generated the implementation and automated tests. AI use was substantial and is described below.

## Tools and setup

| Tool | How it was used |
|---|---|
| **ChatGPT (OpenAI)** | Requirements analysis, architecture discussions, alternatives and trade-offs, sprint specifications, debugging analysis, and review of implementation handoffs. Exact model versions across conversations were not recorded. |
| **Claude Code (Anthropic)** | VS Code extension using **Claude Opus 5.5** (`claude-opus-5-5`). Generated and revised Python code, packaging, tests, CI, helper scripts, and documentation from the agreed specifications and follow-up instructions. |
| **Anthropic API (runtime)** | Optional natural-language intent extraction for `agentctl run workflow --request`. This is part of the application, separate from the development assistant. |

Claude Code used local shell access to install packages, execute CLI commands and `pytest`, and operate `git` and `gh` to prepare commits and pull requests. A third-party `superpowers` skills plugin was installed; its test-driven-development skill was used in Sprint 7. For the optional Anthropic adapter in Sprint 6, Claude Code consulted the `claude-api` reference skill and examined the installed SDK. Claude Code did not have the runtime API key in the recorded implementation sessions; I performed live Anthropic checks separately.

## My engineering role and development process

I separated the assessment's core requirements from optional enhancements and organized the work into seven bounded sprints. My priorities were a **domain-independent SDK**, independently installed namespace-package agents, metadata-driven dependency planning, deterministic sequential execution, and a working weather → clothing advice → SQLite wardrobe example.

I chose to keep application-specific clothing rules outside the core framework. After the basic structured workflows were working, I added optional natural-language intent resolution with a clear boundary: the LLM extracts a goal and parameters, but a generic validator and deterministic planner control execution. I later scoped Sprint 7 to practical office and walking inputs rather than a broader recommendation-system redesign.

Before each sprint, I discussed architecture, interfaces, test expectations, and acceptance criteria with ChatGPT. ChatGPT helped draft the [master plan](../AGENTIC_WORKFLOW_FRAMEWORK_MASTER_PLAN.md) and [sprint specifications](sprints/) based on those decisions. I provided the specifications to Claude Code, considered its implementation handoffs and test findings, requested follow-up changes, and reviewed the pull requests before merging. Claude Code generated the repository's Python source, tests, packaging, GitHub Actions workflow, and most documentation; I do not claim to have handwritten that generated code.

## Runtime AI and disclosure boundaries

The optional `--request` mode calls the Anthropic API to interpret natural language against goals and parameters advertised by installed plugins. Its output is validated before the existing deterministic planner executes the workflow; the LLM does not directly select execution steps or call tools. Structured named and goal-based workflows do not require an Anthropic API key. Credentials are supplied through environment variables and are not included in the repository.

This disclosure distinguishes my design direction, decisions, review, and manual verification from AI-generated implementation. It does not claim line-by-line manual authorship or review. Exact ChatGPT model versions and a precise development-time breakdown were not recorded and are not invented here.
