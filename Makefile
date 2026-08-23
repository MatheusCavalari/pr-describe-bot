run:
	uvicorn app.main:app --reload

test:
	pytest tests/unit -v

lint:
	ruff check .
