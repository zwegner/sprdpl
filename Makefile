PY_SRC = $(wildcard sprdpl/*.py) $(wildcard scripts/*.py)

all : lint

lint : FORCE
	-TERM=dumb bandit $(PY_SRC)
	-pylint --rcfile=.pylintrc $(PY_SRC)

test : FORCE
	bash scripts/test.sh

FORCE :

.PHONY : FORCE all
