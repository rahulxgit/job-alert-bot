"""
Configuration loaded from environment variables and static matching rules.
"""
import os

# Phase 3 AI checkpointing. Existing settings remain backward compatible.
AI_CHECKPOINT_ENABLED = os.environ.get("AI_CHECKPOINT_ENABLED", "true").lower() == "true"
AI_CHECKPOINT_FILENAME = os.environ.get("AI_CHECKPOINT_FILENAME", "ai-progress.json")
AI_FAILED_QUEUE_FILENAME = os.environ.get("AI_FAILED_QUEUE_FILENAME", "failed-ai-jobs.json")
AI_CHECKPOINT_SAVE_EVERY = max(1, int(os.environ.get("AI_CHECKPOINT_SAVE_EVERY", "1")))
