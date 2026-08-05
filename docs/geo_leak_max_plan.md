# Maximum-score Expedia strategy

## Current champion

- Public MAP@5: 0.50920
- Private MAP@5: 0.50506
- Local temporal validation MAP@5: 0.517039
- Model: LightGBM LambdaRank + heuristic + legacy blend

## Why the next stage is not just a larger ranker

Historical top solutions exploited the structure of `orig_destination_distance`. Exact matches already recover a portion of the test set, but the strongest path is to infer hidden hotel/city geometry and extend those matches across related cities and destinations.

## Target architecture

1. Preserve the current champion as fallback.
2. Add fuzzy direct leak matching around exact distance values.
3. Build a city-pair delta graph per destination and market.
4. Reconstruct latent hotel identities by joining consistent distance observations across cities.
5. Run component-wise robust distance completion instead of one global 700 GB optimization.
6. Produce leak candidates with confidence, support and residual-error features.
7. Add those candidates and features to the candidate generator and LambdaRank model.
8. Train multiple time-window and seed variants.
9. Optimize an out-of-fold MAP@5 blend between geometry leak, ranker and frequency models.
10. Submit only candidates that beat the champion on the full temporal validation.

## Validation gates

- No future leakage in local temporal validation.
- Report direct-leak and wide-leak coverage separately.
- Report MAP@5 on covered rows and total MAP@5.
- Compare every experiment to 0.517039 local MAP@5.
- Keep the current Kaggle champion until a new submission beats 0.50920 public and 0.50506 private.

## Hardware policy

The local implementation must fit a 64 GB workstation by processing sparse connected components and DuckDB batches. A full global reconstruction is treated as a separate high-memory cloud experiment.
