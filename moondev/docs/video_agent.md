# Video Agent

Creates video content from trading data.

## What It Does
- Generates video scripts
- Creates chart animations
- Produces market recaps
- Makes educational content

## Usage
```bash
python src/agents/video_agent.py
```

## Video Types
- Daily market recap
- Token deep dives
- Strategy explanations
- Tutorial content

## Features
- Auto-generates thumbnails
- Creates timestamps
- Adds captions
- Exports in multiple formats

## Configuration
```python
VIDEO_LENGTH = 'short'  # 'short' (<60s) or 'long'
VIDEO_STYLE = 'educational'  # or 'news', 'analysis'
```

## Requirements
- FFmpeg
- Optional: GPU for rendering

## Output
`src/data/video_agent/[date]/[title].mp4`