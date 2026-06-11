# Explicit SQL Migrations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a manual SQL migration command, move schema changes into migration files, and stop mutating schema during API startup.

**Architecture:** A lightweight Python CLI reads a chosen SQL file, splits it into statements, and executes them through the existing MySQL connection settings. API startup keeps runtime worker credential syncing but no longer performs DDL.

**Tech Stack:** Python `argparse`, PyMySQL, Python `unittest`, Node.js string-contract tests

---
