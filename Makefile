run:
	uvicorn app.main:app --reload

test:
	pytest tests/unit tests/integration -v

lint:
	ruff check .
