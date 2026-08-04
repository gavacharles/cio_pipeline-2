Place UBOS CIPI monthly Excel workbooks here (one file per release).
Download from: https://www.ubos.org/publications/statistical/  (CIPI Excel Tables link)

Two synthetic example workbooks are included to demonstrate the parser and the
vintage-splicing logic (different layouts, one rebased). They are NOT real data:
  CIPI_2020_06.xlsx           (layout A: 'Jan-2020' headers, labels in col A)
  CIPI_2022_06_rebased.xlsx   (layout B: '2022M01' headers, labels in col B)

Run:  python3 src/index/build_panel.py   to build the panel from whatever is here.
