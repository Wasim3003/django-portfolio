# Wasim Stark portfolio

```
app.py            Django backend (page, contact form, JARVIS, GitHub feed)
index.html        the whole page: styles, content and scripts in labelled sections
resume.pdf        your resume (replace this file to update it)
theme.mp3         music for the Music button (use a track you have the right to use)
requirements.txt  Python packages
render.yaml       deploy settings for Render
```

## Inside index.html
1. `<style>`: all styles, grouped by section (see the comments)
2. The page: header, hero, About, Timeline, Systems, Projects, GitHub, Notes, Game, Contact, footer
3. `<script>` blocks at the bottom: one per feature, each starts with a comment saying what it does

## Run locally
```
pip install -r requirements.txt
python app.py runserver --noreload
```
Open http://127.0.0.1:8000

## Deploy
Push this folder to GitHub, then create a Blueprint on Render. It reads `render.yaml`.
Add your keys in Render's Environment page. Never put keys in the code.
