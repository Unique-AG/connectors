@sharepoint
Feature: Organizing and sharing files in OneDrive and SharePoint
  Mia files documents and shares them with colleagues.
  Mia asks her assistant to create, move, copy, and delete files, and to give other people access.
  Each change asks for Mia's approval first. A delete moves an item to the recycle bin and erases nothing for good.

  Rule: Mia files documents where she wants them

    Scenario: Signed contracts move into a new folder
      Given the folder "Contracts" holds 4 signed contracts
      When Mia asks her assistant to move them into a new folder "2026 Signed"
      Then Mia is asked to approve the change first
      And after she approves, "2026 Signed" holds the 4 contracts with their names

    Scenario: A folder is copied to another drive
      Given Mia has the folder "Template" of 20 files in her OneDrive
      When Mia asks her assistant to copy "Template" into the Sales site
      Then the Sales site holds a copy of "Template" with 20 files
      And "Template" stays in Mia's OneDrive

    Scenario: A delete moves a file to the recycle bin
      Given Mia has the file "Old draft.docx"
      When Mia asks her assistant to delete "Old draft.docx"
      Then "Old draft.docx" is in the recycle bin
      But it is not erased for good

    Scenario: Meeting notes are saved as a new text file
      Given Mia has the folder "Notes"
      When Mia asks her assistant to save these meeting notes as "Sync 14 June.txt" in "Notes"
      Then "Notes" holds "Sync 14 June.txt" with the notes

    @known-gap
    Scenario: The content of an existing file is replaced
      Given Mia has the file "Plan.docx" with an old text
      When Mia asks her assistant to replace the content of "Plan.docx" with a new text
      Then "Plan.docx" holds the new text

  Rule: Mia gives access to a colleague and can take it back

    Scenario: A colleague gets edit access
      Given Mia has the file "Q3 Plan.pptx"
      When Mia asks her assistant to give Anna edit access to "Q3 Plan.pptx"
      Then Mia is asked to approve the access first
      And after she approves, Anna can edit "Q3 Plan.pptx"

    Scenario: A sharing link is created and sent to nobody
      Given Mia has the file "Q3 Plan.pptx"
      When Mia asks her assistant for a sharing link to "Q3 Plan.pptx"
      Then the assistant gives Mia the sharing link
      But nobody receives it from the assistant

    @known-gap
    Scenario: Access is taken back
      Given Anna has edit access to "Q3 Plan.pptx"
      When Mia asks her assistant to stop sharing "Q3 Plan.pptx" with Anna
      Then Anna can no longer open "Q3 Plan.pptx"
