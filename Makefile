.PHONY: lint dev env db deldb

env:
	poetry install

dev:
	poetry run isort .
	poetry run black .

db: deldb
	sudo docker run --name=wikiofbabel -ePOSTGRES_USER=user -ePOSTGRES_PASSWORD=password -ePOSTGRES_DB=wikiofbabel -p5432:5432 -d postgres

deldb:
	sudo docker rm -f -v wikiofbabel || true
