@sharepoint
Feature: Finding and reading files in OneDrive and SharePoint
  Mia and her colleagues keep documents in OneDrive and on SharePoint sites.
  Mia asks her assistant to find a document, to show what a folder holds, and to answer from the content of one file.
  The assistant sees only the files that Mia herself can open.

  Background:
    Given Mia can open her own OneDrive, the Legal site, and the Sales site

  Rule: The assistant finds a file from what Mia remembers about it

    Scenario: A file is found by a word in its name and by its type
      Given the Legal site holds "Brightway Master Agreement.docx" and "Brightway Pricing.xlsx"
      When Mia asks her assistant for the Brightway agreement as a Word document
      Then the assistant shows "Brightway Master Agreement.docx"
      But it does not show "Brightway Pricing.xlsx"

    Scenario: The file that was edited last comes first, with its editor
      Given Mia has quarterly plans edited in January by Anna, in March by Tom, and in May by Priya
      When Mia asks her assistant for the quarterly plan that was edited last
      Then the assistant shows the May plan first
      And it names Priya as the editor

    Scenario: A search stays on the site that Mia names
      Given the Legal site and the Sales site each hold "NDA Template.docx"
      When Mia asks her assistant for the NDA template on the Legal site only
      Then the assistant shows the Legal copy
      But it does not show the Sales copy

    Scenario: A missing file is reported as missing
      Given no file that Mia can open mentions "Zephyr"
      When Mia asks her assistant for the Zephyr budget
      Then the assistant says that it found no matching file

  Rule: The assistant shows what a folder holds, one level at a time

    Scenario: A folder lists its files and subfolders, newest first
      Given the folder "2026 Contracts" holds 12 files and 3 subfolders
      When Mia asks her assistant what "2026 Contracts" holds, newest first
      Then the assistant lists the 12 files and the 3 subfolders, newest first
      But it does not list what is inside the subfolders

  Rule: The assistant answers from the content of one file

    Scenario Outline: The answer comes from the content of the file
      Given Mia has a <kind> that states "the launch date is 14 June"
      When Mia asks her assistant for the launch date in that file
      Then the assistant answers "14 June"

      Examples:
        | kind            |
        | Word document   |
        | Excel workbook  |
        | PowerPoint deck |
        | PDF             |
        | plain text file |

    Scenario: A file that opens through a sharing link is read
      Given Anna sent Mia a sharing link to the deck "Q3 Plan.pptx"
      When Mia asks her assistant to summarize what the sharing link opens
      Then the assistant summarizes "Q3 Plan.pptx"

    Scenario: A file of exactly 10 MB is read
      Given Mia has a PDF of exactly 10 MB
      When Mia asks her assistant to summarize it
      Then the assistant summarizes the PDF

    Scenario: A file above 10 MB is refused as a whole
      Given Mia has a PDF of 10.5 MB
      When Mia asks her assistant to summarize it
      Then the assistant tells Mia that the file is too large to read
      But it does not summarize only a part of the file

    @seen-failing
    Scenario: A file that Microsoft cannot provide is reported and not guessed
      Given Microsoft cannot provide "Brightway Master Agreement.docx" as a PDF
      When Mia asks her assistant for that agreement as a PDF
      Then the assistant tells Mia that the file could not be read
      But it does not invent the content of the file
