CC = clang
CFLAGS = -O2 -std=gnu99 -Wno-deprecated-declarations -Wno-overlength-strings
LDLIBS = -framework OpenCL
SOLVER = solver
OBJECTS = $(SOLVER)/main.o $(SOLVER)/blake.o $(SOLVER)/sha256.o

.PHONY: all clean benchmark devices
all: sa-solver

sa-solver: $(OBJECTS)
	$(CC) -o $@ $(OBJECTS) $(LDLIBS)

$(SOLVER)/main.o: $(SOLVER)/_kernel.h $(SOLVER)/blake.h $(SOLVER)/param.h $(SOLVER)/sha256.h
$(SOLVER)/blake.o: $(SOLVER)/blake.h
$(SOLVER)/sha256.o: $(SOLVER)/sha256.h

$(SOLVER)/_kernel.h: $(SOLVER)/input.cl $(SOLVER)/param.h
	{ printf 'const char *ocl_code = R"_mrb_(\n'; clang -E -P -x c $(SOLVER)/input.cl; printf ')_mrb_";\n'; } > $@

devices: sa-solver
	./sa-solver --list

benchmark: sa-solver
	./sa-solver --nonces 100

clean:
	rm -f sa-solver $(OBJECTS) $(SOLVER)/_kernel.h
