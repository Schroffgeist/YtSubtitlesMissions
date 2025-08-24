# LLM Text Distillation Script - Complete Usage Guide

## Overview
The `distill_cli_resumm-Y-comp-995.py` script is a powerful tool for recursively summarizing large collections of text files using Gemini AI. It's designed for processing hundreds/thousands of files like YouTube subtitles, transcripts, blog posts, or news articles.

## Quick Start Examples

### 1. Basic Processing - YouTube Subtitles
```bash
# Process all cleaned VTT files in parent directory
python distill_cli_resumm-Y-comp-995.py \
  --source-dir ../ \
  --extension .cleaned.vtt \
  --output-dir ./bitcoin_analysis \
  --model gemini-1.5-flash
```

### 2. Resume Long-Running Jobs
```bash
# Resume processing if interrupted
python distill_cli_resumm-Y-comp-995.py \
  --source-dir ~/Documents/source_texts \
  --resume \
  --max-workers 5
```

### 3. Smart Batching for Large Files
```bash
# Optimized for financial reports (large files)
python distill_cli_resumm-Y-comp-995.py \
  --batch-mode size \
  --max-batch-size-kb 20000 \
  --large-file-threshold-kb 15000 \
  --batch-size 10
```

## Detailed Parameter Explanations

### Directory Settings
- **`-s, --source-dir`**: Root folder containing your text files
- **`-o, --output-dir`**: Where processed files are saved
- **`-e, --extension`**: Target file extension (filtering)

### AI Configuration
- **`-m, --model`**: Gemini model to use
  - `gemini-1.5-flash` - Fast & cost-effective
  - `gemini-1.5-pro` - Higher quality, more expensive
- **`--prompt-file`**: Custom AI instructions file

### Batching Modes Explained

#### 1. Count Mode (`--batch-mode count`)
- **When to use**: When files are similar size (news articles)
- **How it works**: Fixed number of files per batch
- **Parameters**:
  - `--batch-size 25` = exactly 25 files per batch

Example:
```bash
# Process 50 blog posts at a time
python distill_cli_resumm-Y-comp-995.py \
  --source-dir ./blog_posts \
  --batch-mode count \
  --batch-size 50
```

#### 2. Size Mode (`--batch-mode size`)
- **When to use**: Mixed file sizes (reports, variable content)
- **How it works**: Greedy packing by total size
- **Parameters**:
  - `--max-batch-size-kb 15000` = Max 15MB per batch
  - `--large-file-threshold-kb 10000` = Single-file batches for large files

Example:
```bash
# Process legal documents with size limits
python distill_cli_resumm-Y-comp-995.py \
  --source-dir ./legal_docs \
  --batch-mode size \
  --max-batch-size-kb 10000 \
  --large-file-threshold-kb 8000
```

#### 3. Balanced Mode (`--batch-mode balanced`)
- **When to use**: Need evenly distributed workload
- **How it works**: Heap algorithm for optimal size distribution
- **Parameters**: `--batch-size` acts as max files per batch

Example:
```bash
# Even distribution across 24-hour processing
python distill_cli_resumm-Y-comp-995.py \
  --source-dir ./news_articles \
  --batch-mode balanced \
  --batch-size 30
```

## Real-World Usage Scenarios

### Scenario 1: Financial Analysis Pipeline
```bash
# Daily crypto analysis from multiple YouTube channels
python distill_cli_resumm-Y-comp-995.py \
  --source-dir "../UC0-FJ8lpggmZVgUC5Nb-gWg.PumaFinanzas.Puma Finanzas - Live/" \
  --extension .cleaned.vtt \
  --output-dir ./daily_crypto_summaries \
  --model gemini-1.5-flash \
  --batch-mode size \
  --max-batch-size-kb 12000 \
  --max-workers 4
```

### Scenario 2: Academic Research
```bash
# Process 1000 scientific papers
python distill_cli_resumm-Y-comp-995.py \
  --source-dir ~/research/papers_2024 \
  --extension .txt \
  --output-dir ./research_summary \
  --model gemini-1.5-pro \
  --batch-mode balanced \
  --batch-size 15 \
  --timeout 1200
```

### Scenario 3: Live Podcast Processing
```bash
# Resume nightly podcast processing
python distill_cli_resumm-Y-comp-995.py \
  --source-dir /var/plex/podcasts \
  --extension .srt \
  --output-dir ./nightly_summaries \
  --resume \
  --batch-mode size \
  --max-workers 6
```

## Performance Tuning

### Memory Optimization
```bash
# Low-resource environment settings
python distill_cli_resumm-Y-comp-995.py \
  --max-workers 2 \
  --batch-size 10 \
  --max-batch-size-kb 5000 \
  --timeout 300
```

### High-Performance Processing
```bash
# Maximum throughput (powerful machine)
python distill_cli_resumm-Y-comp-995.py \
  --max-workers 8 \
  --batch-size 50 \
  --max-batch-size-kb 25000 \
  --timeout 900
```

## Monitoring Progress

### Expected Output Pattern
```
--- LLM Distillation Script Initializing ---
Configuration:
  - Extension: .vtt
  - Max workers: 4
  - Model: gemini-1.5-flash
  - Source directory (resolved): [your_path]
  - Output directory (resolved): [your_path]/distilled_output
--------------------------------------------

--- Starting Round 1 ---
Processing 47 files in this round.
Divided into 3 batches using 'size' mode.
  -> Processing Batch 1 (Round 1) - 16 files, 1024.50 KB...
     Success! Saved distilled output to: round_1_batch_1.txt
  -> Processing Batch 2 (Round 1) - 15 files, 980.25 KB...
     Success! Saved distilled output to: round_1_batch_2.txt
```

## Advanced Workflow Patterns

### 1. Staged Processing
```bash
# Stage 1: Quick summary
python distill_cli_resumm-Y-comp-995.py \
  --source-dir articles/2024/q1 \
  --model gemini-1.5-flash \
  --output-dir ./stage1_quick

# Stage 2: Detailed analysis
python distill_cli_resumm-Y-comp-995.py \
  --source-dir ./stage1_quick \
  --model gemini-1.5-pro \
  --output-dir ./final_detailed
```

### 2. Monitoring System
```bash
# Create alias for common config
alias distill_daily='python ~/dev/distiller/distill_cli_resumm-Y-comp-995.py'

# Daily run script
distill_daily \
  --source-dir ~/data/daily_podcasts \
  --extension .vtt \
  --output-dir ~/summaries/$(date +%Y-%m-%d) \
  --resume
```

### 3. Batch Script Integration
```bash
#!/bin/bash
# file: run_distillation.sh
PROJECT_DIR="$1"
OUTPUT_SUFFIX="$2"

echo "Starting distillation for: $PROJECT_DIR"
python distill_cli_resumm-Y-comp-995.py \
  --source-dir "$PROJECT_DIR" \
  --extension .cleaned.vtt \
  --output-dir "./summaries/${OUTPUT_SUFFIX}" \
  --batch-mode balanced \
  --batch-size 20 \
  --resume
```

## Debugging Common Issues

### 1. "gemini command not found"
```bash
# Check installation
gemini --version

# If not installed:
gem install gemini-cli
# OR setup gemini-bin
```

### 2. "No files found"
```bash
# Verify extension match
find ./content -name "*.vtt" | wc -l
ls -la ../ | grep -i "\.cleaned\.vtt$"

# Try with different extension
--extension .vtt --extension .srt --extension .txt
```

### 3. Batch too large
```bash
# Reduce batch size
--max-batch-size-kb 8000
--batch-size 12
```

### 4. Timeout issues
```bash
# Increase timeout for complex content
--timeout 1200

# Reduce batch size
--batch-size 8
```

## Creating Custom Prompts

### Template Structure:
```text
# prompt_custom.txt
You are a specialized [TOPIC] analyst. Analyze the provided documents and create:
1. Executive summary
2. Key findings
3. Actionable insights
4. Timeline of events

Format: Markdown with tables where appropriate.
Maximum length: 5000 words
Focus: [specific_focus]
```

### Usage:
```bash
python distill_cli_resumm-Y-comp-995.py \
  --prompt-file prompt_custom.txt \
  --output-dir ./custom_analysis/
```

## Example Complete Workflows

### 1. YouTube Channel Analysis (Crypto)
```bash
# Setup
mkdir -p analysis/crypto_youtube/{source,distilled}
cd analysis/crypto_youtube

# Run analysis
python ~/dev/distiller/distill_cli_resumm-Y-comp-995.py \
  --source-dir source/UC0-FJ8lpggmZVgUC5Nb-gWg.PumaFinanzas/ \
  --extension .cleaned.vtt \
  --output-dir ./distilled/2024_summary \
  --batch-mode balanced \
  --batch-size 25 \
  --model gemini-1.5-pro

# Monitor
watch -n 30 'ls -la ./distilled/2024_summary/ | wc -l'
```

### 2. Research Paper Processing
```bash
# For a 200-paper conference
python distill_cli_resumm-Y-comp-995.py \
  --source-dir ./acl_2024_papers/ \
  --extension .txt \
  --output-dir ./acl_summary/ \
  --batch-mode size \
  --max-batch-size-kb 20000 \
  --max-workers 6 \
  --model gemini-1.5-pro
```

### 3. Podcast Network Analysis
```bash
# Processing multiple shows
for show_dir in ../podcasts/*/; do
  show_name=$(basename "$show_dir")
  python distill_cli_resumm-Y-comp-995.py \
    --source-dir "$show_dir" \
    --extension .srt \
    --output-dir "./show_summaries/$show_name" \
    --batch-mode balanced \
    --batch-size 15 \
    --resume
done
```

## Final Tips

1. **Start small**: Test with 10-20 files first
2. **Use resume**: Always include `--resume` for large runs
3. **Monitor costs**: Gemini Pro is expensive, Flash is 15x cheaper
4. **Backup prompts**: Keep your custom prompts under version control
5. **Pipeline thinking**: Build automated workflows for recurring analyses




python distill_cli_resumm-Y-comp-995.py \
  --max-batch-size-kb 1700 \
  --batch-size 55 \
  --resume
