import express from 'express';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';

const app = express();
app.use(express.json());

const port = Number(process.env.PORT ?? 80);
const dataDir = process.env.DATA_DIR ?? '/app/data';
const file = `${dataDir}/notes.json`;
const load = () => (existsSync(file) ? JSON.parse(readFileSync(file, 'utf8')) : []);

app.get('/health', (_req, res) => res.type('text').send('ok'));
app.get('/notes', (_req, res) => res.json(load()));
app.post('/notes', (req, res) => {
  const notes = load();
  notes.push({ text: String(req.body?.text ?? '') });
  mkdirSync(dataDir, { recursive: true });
  writeFileSync(file, JSON.stringify(notes));
  res.status(201).json(notes.at(-1));
});

app.listen(port, () => console.log(`notes-api listening on ${port}`));
