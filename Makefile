.PHONY: lint dev env db deldb

env:
	poetry install

dev:
	poetry run isort .
	poetry run black .

resetdb:
	sudo docker rm -f -v wikiofbabel || true
	sudo docker run --name=wikiofbabel -ePOSTGRES_USER=user -ePOSTGRES_PASSWORD=password -ePOSTGRES_DB=wikiofbabel -p5432:5432 -d postgres
