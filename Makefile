BENCHMARKS = b1 b2 b3 b4 b5 b6 b7 php3 php4 php5 php6
NON_SNF_BENCHMARKS = b3 php3 php4 php5 php6

NAIVE_TARGETS = $(foreach b,$(BENCHMARKS),$(b)_naive)
STRUCTURED_TARGETS = $(foreach b,$(BENCHMARKS),$(b)_structured)
ALL_TARGETS = $(NAIVE_TARGETS) $(STRUCTURED_TARGETS)
CVC5_TARGETS = $(foreach b,$(BENCHMARKS),$(b)_structured_cvc5)
NON_SNF_TARGETS = $(foreach b,$(NON_SNF_BENCHMARKS),$(b)_nonsnf)

# Define the corpus directory
CORPUS_DIR = corpus-study/repo_src

.PHONY: all z3 z3_snf z3_non_snf z3_plot cvc5 cvc5_structured compare clean calligraph pipeline $(ALL_TARGETS) $(CVC5_TARGETS) $(NON_SNF_TARGETS)

all: z3 cvc5

pipeline:
	rm -rf snf-pipeline/results
	./snf-pipeline/sweep_corpus.sh corpus-study/repo_src
	python3 snf-pipeline/inspect_gaps.py snf-pipeline/results/results.csv snf-pipeline/results/inspect.txt
	python3 snf-pipeline/test_pipeline.py 

z3: z3_snf z3_non_snf z3_plot

z3_snf: $(ALL_TARGETS)

z3_non_snf: $(NON_SNF_TARGETS)

z3_plot:
	python3 z3-solver/plot_results.py \
		--results z3-solver/results/ \
		--outdir z3-solver/figures/
	python3 z3-solver/non_snf_data/plot_threeway.py
	python3 z3-solver/non_snf_data/plot_sigma_vs_size.py
	python3 z3-solver/non_snf_data/gen_mbqi_table.py > z3-solver/figures/mbqi_table.md

cvc5: cvc5_structured compare

cvc5_structured: $(CVC5_TARGETS)

compare:
	python3 cvc5-solver/plot_comparision.py \
		--z3_results z3-solver/results/ \
		--cvc5_results cvc5-solver/results/ \
		--outdir cvc5-solver/figures/

clean:
	rm -f z3-solver/results/*.json \
		  z3-solver/figures/*.png \
		  z3-solver/figures/*.md \
		  z3-solver/results_nonsnf/*.json \
		  cvc5-solver/results/*.json \
		  cvc5-solver/figures/*.png \
		  cvc5-solver/figures/*.md

# New command to check all 33 corpus repos
calligraph:
	@echo "Starting calligraph check on all repositories in $(CORPUS_DIR)..."
	@for repo in $(CORPUS_DIR)/*; do \
		if [ -d "$$repo" ]; then \
			echo "Checking $$repo..."; \
			python tdc_calligraph_check.py "$$repo"; \
		fi \
	done
	@echo "Finished checking all repositories."

$(ALL_TARGETS):
	@TARGET_TYPE=$$(echo $@ | sed 's/.*_//'); \
	BENCH_NAME=$$(echo $@ | sed 's/_.*//'); \
	python3 z3-solver/mutate_sweep.py \
		--smt benchmarks/$${BENCH_NAME}_$${TARGET_TYPE}.smt2 \
		--label $@ \
		--n 50 \
		--timeout 60 \
		--outdir z3-solver/results/

$(CVC5_TARGETS):
	@BENCH_NAME=$$(echo $@ | sed 's/_structured_cvc5//'); \
	python3 cvc5-solver/mutate_sweep.py \
		--smt benchmarks/$${BENCH_NAME}_structured.smt2 \
		--label $${BENCH_NAME}_structured \
		--n 50 \
		--timeout 60 \
		--outdir cvc5-solver/results/

$(NON_SNF_TARGETS):
	python3 z3-solver/mutate_sweep.py \
		--smt z3-solver/non_snf/$@.smt2 \
		--label $@ \
		--n 50 \
		--timeout 60 \
		--outdir z3-solver/results_nonsnf/

# make -j$(nproc) all