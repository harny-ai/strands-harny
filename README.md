# strands-harny

Harny gives every customer of your app their own AI agent, one that knows that customer and acts for them. This package brings the part that knows each customer to Strands agents: long-term memory that keeps up when facts change.

## Install

```bash
pip install strands-harny
```

Python 3.10+. Needs `strands-agents>=1.66.0`.

## Start without a key

You do not need an account first. From the project folder:

```bash
pip install harny
harny init --name "<business>" --about "<what the app does>" --customers "<who its customers are>"
```

That creates the app and saves `HARNY_API_KEY` to `.env` without printing it. Never print, log or commit the key. (Raw API route: `POST https://api.harny.ai/v1/auth/provision` with `{"app_name": "<business>"}`; the key is shown once.)

## Usage

```python
from strands import Agent
from strands.memory import MemoryManager
from strands_harny import HarnyMemoryStore

store = HarnyMemoryStore(user="nadia")  # reads HARNY_API_KEY; "nadia" is YOUR id for the person
agent = Agent(memory_manager=MemoryManager(stores=[store]))
agent("What is the Acme pilot budget?")
```

`user` is your own id for the person. The API reads only that person's memory, so one app key can serve every user safely.

## Options

| Argument | Default | Meaning |
|---|---|---|
| `user` | required | Your id for the person |
| `api_key` | `HARNY_API_KEY` | App key (`fsa_`) |
| `base_url` | `https://api.harny.ai` | Harny API address |
| `level` | `medium` | How much evidence to recall (`low`, `medium`, `high`, `extra-high`) |
| `name`, `description`, `max_search_results`, `writable`, `extraction` | see Strands | The standard `MemoryStoreConfig` fields |

## Behaviour an agent should know

- **Save what the person says.** Set `extraction=True` and later runs recall it; only the person's own messages are sent, never the model's replies or system text. It is off by default.
- **A saved fact has a stable id** (hash of the person and the words), so saying the same words twice is one fact and costs nothing the second time.
- **A memory problem never fails the run.** If recall is refused, the agent answers without memory and one warning with the error code is logged (never content, never keys).

## Tests

```bash
pip install -e ".[dev]"
pytest
```

The tests make no network call and no paid call.

Apache-2.0. https://harny.ai
