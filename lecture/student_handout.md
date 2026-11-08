# Project 1 · Student Handout

**Big Data Analytics: from social-media records to a marketing decision**

## The situation

A Pakistani clothing brand posts on Instagram. The marketing team wants to understand **which content receives attention** and **what it should publish next**.

You will answer this with ordinary tools (CSV, Google Colab, Pandas) on a small dataset. Then you will make the data bigger and measure what changes. By the end you should be able to say when a scalable tool such as Spark might help, and when it would not.

You will **not** start with Hadoop or Spark.

## What you hand in

Your instructor may change the format. A suggested format:

1. Your completed notebook (`project1_notebook.ipynb`, with outputs showing).
2. A short report (1-2 pages) with your data dictionary, two observations, one recommendation, and one limitation.
3. `my_data_dictionary.csv` and `my_scaling_results.csv` (the notebook creates both).

### Submission checklist
- [ ] Dataset source, license/provenance note, and data dictionary
- [ ] Record count, column types, missing-value and duplicate checks
- [ ] At least two summary statistics and two useful charts
- [ ] Two evidence-based observations and one marketing recommendation
- [ ] One limitation and a reason a scalable tool might help at larger scale

### Marking (10 marks)

| Criterion | Marks | What to show |
|---|---|---|
| Data understanding and course concepts | 1 | What one record is; column types; data sources and types of data |
| Cleaning and quality checks | 1 | Duplicates, missing values, impossible values, and what you decided about each |
| EDA and statistics | 2 | Counts, mean and median, group comparisons that fit the data |
| Charts and interpretation | 2 | At least two readable charts with titles and labels, and what each one shows |
| Scaling experiment and tool justification | 2 | Your own timings and memory, and a reasoned view on when a scalable tool might help |
| Analytics concept, recommendation, and presentation | 2 | Which of classification, clustering, or regression would help; a clear recommendation |
| **Total** | **10** | |

The "What to show" column is a guide to help you aim, not extra rules.

## Step by step

### Step 1-2 · Understand the project
Read the situation above. Every topic in the course appears somewhere in this project: data sources, types of data, EDA, plots and statistics, and analytics techniques. As you work, note where each one shows up.

### Step 3 · Get the dataset
Demo repository: [mrudukp/social-media-sentiment-analysis](https://github.com/mrudukp/social-media-sentiment-analysis)

Before you use it, write a **provenance note**:
- Where did the file come from (repository, author)?
- Is there a license? (The repository page shows none, so write "no license stated" unless you find one.)
- What does it NOT tell you? (It is not verified as data from a Pakistani brand, and it does not say how the data was collected.)

### Step 4 · Load it in Colab
1. Open the repository and read its README.
2. Download `social_media_sentiment_raw.csv`.
3. Open the notebook in Google Colab and run the first cells. Upload the CSV when asked.
4. **Check the column names before writing any analysis.** Do not assume them.
5. Keep a backup copy of the original file. The notebook makes one for you.

### Step 5 · Understand the data
- Answer: **what is one record?** (A post, a comment, a user, or a campaign? They are not the same.)
- Check shape, column types, missing values, and duplicates.
- Classify each column as numerical, categorical, text, date/time, or identifier.
- Complete your data dictionary (the notebook builds a starting table).
- **Do not delete missing values automatically.** A blank metric may mean "not collected," not zero.

### Step 6 · Explore
Pick **two or three** analyses that your columns can really support. Ideas:
- Which platforms are most represented?
- Median vs mean likes and comments: what is typical?
- Are a few posts dominating the averages?
- Is there a relationship between likes and comments?

Two rules:
- No usable date field means no claims about the best posting day.
- No reach or impressions means no engagement rate based on reach.

### Step 7 · Say what it means
Write one statement in this form:

| Part | Question |
|---|---|
| **Finding** | What pattern do you actually see in this dataset? |
| **Evidence** | Which count, statistic, or chart supports it? |
| **Action** | What should a marketer test next? |
| **Limitation** | What can't this dataset tell us? |

Do not say a type of content is "best" just because its total likes are higher. Check how many posts are in each group, and whether you have reach, impressions, or audience-size information.

### Step 8 · Scale it
Run the same analysis on 1x, 10x, and 100x copies of your data (1000x only if your computer has the memory). Record:
- File size and number of rows
- Time to load and time to analyse
- Memory use
- Which operation became slow or inconvenient
- Whether the data still fits in memory

Use the notebook cells, or run `python scaling_experiment.py --csv your_file.csv`.

Remember:
- Repeated copies are a **scaling experiment**, not new real-world evidence.
- Pandas may handle millions of rows on some computers. There is no universal row count at which it "fails."
- Spark is worth investigating when data volume, processing time, or distributed storage needs justify it. It is not needed for a 2,000-row file. Use **your numbers** to argue the point.

### Step 9 · Connect to analytics
Read the short demos in the notebook. Then answer in 2-3 sentences: **which of classification, clustering, or regression would help answer your marketing question, and what evidence would you need?**

Avoid data leakage: do not use a metric to build a label and then present the same metric as a meaningful independent prediction. Always split data into training and test sets for predictive work.

### Step 10 · Finish
Check the submission list above. Then answer the closing question in your report:

> **What does the data tell us, what business problem does it reveal, and what should the business do next?**

## Common mistakes

- Using the README's "key insights" instead of your own results.
- Making claims about Pakistan from a dataset that is not verified as Pakistani.
- Comparing groups by total likes without looking at how many posts each group has.
- Filling or deleting missing values without saying why.
- Calling a scaling experiment on repeated rows "new evidence."
- Saying Spark is needed because "big data is better," with no measurements to back it up.

## Optional

- Class hashtag: `#UMTDataDetective`. Posting publicly is optional. You can submit privately instead.

## Coming next

The next project adds genuine or clearly labelled sample paid-campaign data (spend, impressions, clicks, conversions) before moving to Meta Ads and Google Ads analysis. Organic engagement data alone cannot calculate ROAS or paid-ad performance.
