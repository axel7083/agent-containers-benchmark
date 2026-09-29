import express from 'express';

const app = express();
const port = Number(process.env.PORT ?? 8080);
const items = [
  { id: 1, name: 'widget', stock: 12 },
  { id: 2, name: 'gadget', stock: 0 },
];

app.get('/health', (_req, res) => res.type('text').send('ok'));
app.get('/items', (_req, res) => res.json(items));
app.get('/items/:id', (req, res) => {
  const item = items.find(i => i.id === Number(req.params.id));
  return item ? res.json(item) : res.status(404).json({ error: 'not found' });
});

app.listen(port, () => console.log(`inventory-api listening on ${port}`));
