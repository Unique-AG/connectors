@sharepoint
Feature: Organizing and sharing files in OneDrive and SharePoint
  Mia files documents and shares them with colleagues.
  Mia asks her assistant to create, move, copy, and delete files, and to give other people access.
  Each change asks for Mia's approval first. A delete moves an item to the recycle bin and erases nothing for good.

  Rule: Mia files documents where she wants them

    @happy @uc-10-01
    Scenario: Signed contracts move into a new folder
      Given the folder "Contracts" holds 4 signed contracts
      When Mia asks her assistant to move them into a new folder "2026 Signed"
      Then Mia is asked to approve each change first
      And after she approves, "2026 Signed" holds the 4 contracts with their names

    @happy @uc-10-02
    Scenario: A folder is copied to another drive
      Given Mia has the folder "Template" of 20 files in her OneDrive
      When Mia asks her assistant to copy "Template" into the Sales site
      Then the Sales site holds a copy of "Template" with 20 files once the copy is done
      And "Template" stays in Mia's OneDrive

    @happy @uc-10-03
    Scenario: A delete moves a file to the recycle bin
      Given Mia has the file "Old draft.docx"
      When Mia asks her assistant to delete "Old draft.docx"
      Then "Old draft.docx" is in the recycle bin
      But it is not erased for good

    @happy @uc-10-04
    Scenario: Meeting notes are saved as a new text file
      Given Mia has the folder "Notes"
      When Mia asks her assistant to save these meeting notes as "Sync 14 June.txt" in "Notes"
      Then Mia is asked to approve the file first
      And after she approves, "Notes" holds "Sync 14 June.txt" with the notes

    @happy @uc-10-05
    Scenario: The content of an existing file is replaced
      Given Mia has the file "Plan.docx" with an old text
      When Mia asks her assistant to replace the content of "Plan.docx" with a new text
      Then "Plan.docx" holds the new text

    @happy @uc-10-09
    Scenario: A file is renamed and stays in its folder
      Given Mia has the file "Plan v1.docx" in the folder "Projects"
      When Mia asks her assistant to rename "Plan v1.docx" to "Plan v2.docx"
      Then Mia is asked to approve the change first
      And after she approves, "Projects" holds "Plan v2.docx"
      But "Projects" no longer holds "Plan v1.docx"

    @happy @uc-10-10
    Scenario: A file attached to a mail is saved in a folder
      Given Anna sent Mia a mail with the attached file "Offer.pdf"
      And Mia has the folder "Tenders"
      When Mia asks her assistant to save the attached file in "Tenders"
      Then "Tenders" holds "Offer.pdf"

  Rule: Mia gives access to a colleague

    @happy @uc-10-06
    Scenario: A colleague gets edit access
      Given Mia has the file "Q3 Plan.pptx"
      When Mia asks her assistant to give Anna edit access to "Q3 Plan.pptx"
      Then Mia is asked to approve the access first
      And after she approves, Anna can edit "Q3 Plan.pptx"
      And Anna receives an invitation by mail

    @happy @uc-10-07
    Scenario: A sharing link is created and sent to nobody
      Given Mia has the file "Q3 Plan.pptx"
      When Mia asks her assistant for a view-only sharing link to "Q3 Plan.pptx"
      Then Mia is asked to approve the link first
      And after she approves, the assistant gives Mia the sharing link
      But nobody receives it from the assistant

    @happy @uc-10-08
    Scenario: Access is taken back
      Given Anna has edit access to "Q3 Plan.pptx"
      When Mia asks her assistant to stop sharing "Q3 Plan.pptx" with Anna
      Then Anna can no longer open "Q3 Plan.pptx"

  Rule: Mia is told what happened when Microsoft cannot do what she asked
    A change that Microsoft fails can already be done, so the assistant checks before it tries again.

    @unhappy @uc-10-11
    Scenario Outline: A folder that Microsoft will not open for a new file is explained to Mia
      Given Mia has the folder "Notes"
      And Microsoft <problem> when the assistant opens the folder to save a file in it
      When Mia asks her assistant to save these meeting notes as "Sync 14 June.txt" in "Notes"
      Then the assistant tells Mia <told>
      But no file is created

      Examples:
        | problem                             | told                                                                                         |
        | says that Mia's sign-in has expired | to sign in again                                                                             |
        | answers that the folder is gone     | that the folder was probably deleted or moved, and that the assistant finds the folder again |

    @unhappy @uc-10-35
    Scenario: A file that Microsoft refuses to save in a folder is explained to Mia
      Given Mia can open the folder "Notes" but has no right to add a file to it
      When Mia asks her assistant to save these meeting notes as "Sync 14 June.txt" in "Notes"
      Then Mia is asked to approve the file first
      And after she approves, the assistant tells Mia that Microsoft refused, that Mia may lack access or a rule of her organization may block it, and that the owner of the folder can give her more access
      But no file is created

    @unhappy @uc-10-12
    Scenario Outline: A name that is already used creates nothing
      Given the folder "Notes" already holds <existing>
      When Mia asks her assistant to <change>
      Then the assistant tells Mia that an item with that name is already there
      And it asks Mia for another name
      But nothing new is created

      Examples:
        | existing                        | change                                                    |
        | a file named "Sync 14 June.txt" | save these meeting notes as "Sync 14 June.txt" in "Notes" |
        | a folder named "2026 Signed"    | create a folder "2026 Signed" in "Notes"                  |

    @unhappy @uc-10-13
    Scenario: A busy Microsoft is given the time that it asks for before a save
      Given Mia has the folder "Notes"
      And Microsoft is busy and asks the assistant to wait 30 seconds
      When Mia asks her assistant to save these meeting notes as "Sync 14 June.txt" in "Notes"
      Then the assistant tells Mia that Microsoft is busy and asked it to wait 30 seconds
      But it does not try the save again before the 30 seconds pass

    @unhappy @uc-10-14
    Scenario Outline: A save that Microsoft fails is not repeated at once
      Given Microsoft <problem> when the assistant saves "Sync 14 June.txt" in "Notes"
      When Mia asks her assistant to save these meeting notes as "Sync 14 June.txt" in "Notes"
      Then the assistant tells Mia that it does not know if the file was saved
      And it looks in "Notes" for the file before it tries again
      But it does not save the file a second time at once

      Examples:
        | problem                      |
        | fails with an internal error |
        | does not answer in time      |

    @unhappy @uc-10-15
    Scenario: A file that was saved but cannot be shown is not saved twice
      Given Microsoft saves "Sync 14 June.txt" in "Notes", and then does not show the saved file to the assistant
      When Mia asks her assistant to save these meeting notes as "Sync 14 June.txt" in "Notes"
      Then the assistant tells Mia that the file was saved
      And it finds the file by looking in "Notes"
      But it does not save the file a second time

    @unhappy @uc-10-16
    Scenario: A save that Microsoft rejects is not repeated
      Given Microsoft rejects the save of "Sync 14 June.txt" and gives the reason "the path is too long"
      When Mia asks her assistant to save these meeting notes as "Sync 14 June.txt" in "Notes"
      Then the assistant tells Mia that Microsoft rejected the save, with the reason that Microsoft gave
      But it does not repeat the same save, because it fails the same way

    @unhappy @uc-10-29
    Scenario Outline: A move that Microsoft fails is tried once more
      Given Mia has the file "Q3 Plan.pptx" and the folder "Archive"
      And Microsoft <problem> at the first try and does the move at the second try
      When Mia asks her assistant to move "Q3 Plan.pptx" into "Archive"
      Then Mia is asked to approve the move a second time
      And after she approves, "Archive" holds "Q3 Plan.pptx" once

      Examples:
        | problem                      |
        | fails with an internal error |
        | does not answer in time      |

  Rule: Mia is told why a change is refused before anything happens

    @unhappy @uc-10-17
    Scenario Outline: A name with a sign that Microsoft does not allow is refused
      Given Mia has the folder "Notes"
      When Mia asks her assistant to save these meeting notes as "<name>" in "Notes"
      Then the assistant tells Mia <told>
      And it saves no file with that name

      Examples:
        | name              | told                                                  |
        | Sync: 14 June.txt | that Microsoft does not allow the sign ":" in a name  |
        | Notes?.txt        | that Microsoft does not allow the sign "?" in a name  |
        | ~$Sync.txt        | that a name must not start with "~$"                  |

    @unhappy @uc-10-18
    Scenario Outline: Only a text file is created
      Given Mia has the folder "Notes"
      When Mia asks her assistant to save these meeting notes as "<name>" in "Notes"
      Then the assistant tells Mia that it can create text files only, and cannot create <kind>
      And it creates no file

      Examples:
        | name              | kind                           |
        | Sync 14 June.docx | a Word file                    |
        | Budget.xlsx       | an Excel file                  |
        | Offer.pdf         | a PDF file                     |
        | Sync 14 June      | a file without a text ending   |

    @happy @uc-10-19
    Scenario: A text of exactly one million characters is saved
      Given Mia has the folder "Notes" and a text of exactly one million characters
      When Mia asks her assistant to save that text as "Log.txt" in "Notes"
      Then "Notes" holds "Log.txt" with the whole text

    @unhappy @uc-10-20
    Scenario: A text of one million and one characters is refused
      Given Mia has the folder "Notes" and a text of one million and one characters
      When Mia asks her assistant to save that text as "Log.txt" in "Notes"
      Then the assistant tells Mia that the text is too long and that the limit is one million characters
      But no file is created

    @unhappy @uc-10-21
    Scenario Outline: The top folder of a library is not changed
      Given the Sales site holds a library with a top folder
      When Mia asks her assistant to <action> the top folder of that library
      Then the assistant tells Mia that Microsoft does not allow this for the top folder
      And it suggests this instead: <instead>
      But nothing changes

      Examples:
        | action | instead                                              |
        | move   | move each item inside the folder                     |
        | rename | rename a file or a folder inside the library         |
        | copy   | copy the items inside the folder one at a time       |
        | delete | delete a file or a folder inside the library         |

    @unhappy @uc-10-22
    Scenario: A move to another drive becomes a copy
      Given Mia has the file "Q3 Plan.pptx" in her OneDrive
      When Mia asks her assistant to move "Q3 Plan.pptx" into a folder of the Sales site
      Then the assistant tells Mia that a move works inside one drive only, so it copies the file
      And it tells Mia that the copy holds only the latest version of the file
      And it deletes the original only after the copy shows in the Sales site

    @unhappy @uc-10-23
    Scenario: A file that is already in the folder is not moved
      Given Mia has the file "Plan v1.docx" in the folder "Projects"
      When Mia asks her assistant to move "Plan v1.docx" into "Projects"
      Then the assistant tells Mia that the file is already in "Projects"
      But nothing changes

    @happy @uc-10-24
    Scenario: A copy in the same folder gets a new name
      Given Mia has the file "Template.docx" in the folder "Projects"
      When Mia asks her assistant to copy "Template.docx" into "Projects"
      Then "Projects" holds "Template.docx" and a copy with a different name
      But "Template.docx" keeps its name

    @unhappy @uc-10-25
    Scenario: A file that is already gone is not deleted again
      Given somebody else deleted the file "Old draft.docx" a moment ago
      When Mia asks her assistant to delete "Old draft.docx"
      Then the assistant looks for the file again
      And it tells Mia that the file is already gone and that nothing is left to delete

    @unhappy @uc-10-26
    Scenario: A person named without a mail address is not invited
      Given Mia has the file "Q3 Plan.pptx"
      And nobody called Anna at Brightway is in Mia's contacts or in the company directory
      When Mia asks her assistant to give "Anna at Brightway" edit access to "Q3 Plan.pptx"
      Then the assistant asks Mia which mail address it must use
      But nothing is shared and nobody is invited

    @unhappy @uc-10-27
    Scenario: An invitation that may be out is not sent again
      Given Microsoft does not answer in time when the assistant gives Anna edit access to "Q3 Plan.pptx"
      When Mia asks her assistant to give Anna edit access to "Q3 Plan.pptx"
      Then the assistant tells Mia that it does not know if Anna received an invitation
      And it asks Mia to check in the Microsoft 365 app if Anna has access
      But it does not send the invitation a second time before Mia answers

    @unhappy @uc-10-28
    Scenario: A link without sign-in that the organization blocks is explained
      Given the organization of Mia blocks sharing links that work without sign-in
      When Mia asks her assistant for a sharing link to "Q3 Plan.pptx" that anyone can open
      Then the assistant tells Mia that her organization blocks that kind of link
      And it asks Mia if a link for the people of her organization is enough
      But no link is created

  Rule: A change that Mia does not approve does not happen

    @unhappy @uc-10-30
    Scenario Outline: A declined change leaves everything as it was
      Given Mia has the items that the change names
      When Mia asks her assistant to <change>
      Then Mia is asked to approve the change, and she declines
      And the assistant tells Mia that the change was not approved, and does not ask again unless Mia asks in a new message
      But <unchanged>

      Examples:
        | change                                                    | unchanged                                    |
        | move "Contract A.pdf" into "2026 Signed"                  | "Contract A.pdf" is still in "Contracts"     |
        | delete "Old draft.docx"                                   | "Old draft.docx" is not in the recycle bin   |
        | rename "Plan v1.docx" to "Plan v2.docx"                   | the file still has the name "Plan v1.docx"   |
        | give Anna edit access to "Q3 Plan.pptx"                   | Anna receives no invitation                  |
        | save these meeting notes as "Sync 14 June.txt" in "Notes" | "Notes" does not hold "Sync 14 June.txt"     |

    @unhappy @uc-10-31
    Scenario Outline: A change without an answer from Mia does not happen
      Given Mia has the items that the change names
      When Mia asks her assistant to <change>
      Then Mia is asked to approve the change, and no answer comes back
      And the assistant tells Mia that no answer came and that she can ask for the same change again
      But <unchanged>

      Examples:
        | change                                                    | unchanged                                    |
        | move "Contract A.pdf" into "2026 Signed"                  | "Contract A.pdf" is still in "Contracts"     |
        | delete "Old draft.docx"                                   | "Old draft.docx" is not in the recycle bin   |
        | rename "Plan v1.docx" to "Plan v2.docx"                   | the file still has the name "Plan v1.docx"   |
        | give Anna edit access to "Q3 Plan.pptx"                   | Anna receives no invitation                  |
        | save these meeting notes as "Sync 14 June.txt" in "Notes" | "Notes" does not hold "Sync 14 June.txt"     |

    @unhappy @uc-10-32
    Scenario: An approval for another change authorizes nothing
      Given Mia has the file "Plan v1.docx"
      When Mia asks her assistant to rename "Plan v1.docx" to "Plan v2.docx"
      Then Mia is asked to approve the rename, and the answer that comes back was given for another question
      And the assistant asks Mia again for exactly the change that she approves
      But "Plan v1.docx" keeps its name

  Rule: An invitation note has a length limit

    @happy @uc-10-33
    Scenario: A note of exactly 2000 characters goes out with the invitation
      Given Mia has the file "Q3 Plan.pptx" and a note of exactly 2000 characters
      When Mia asks her assistant to give Anna edit access to "Q3 Plan.pptx" with that note
      Then Mia is asked to approve the access first
      And after she approves, Anna receives an invitation with the whole note

    @unhappy @uc-10-34
    Scenario: A note of 2001 characters stops the invitation
      Given Mia has the file "Q3 Plan.pptx" and a note of 2001 characters
      When Mia asks her assistant to give Anna edit access to "Q3 Plan.pptx" with that note
      Then the assistant tells Mia that the note is too long and that the limit is 2000 characters
      But nothing is shared and nobody is invited

  Rule: Mia is told when the assistant lacks a permission that an administrator must give

    @unhappy @uc-10-36
    Scenario: A permission that no administrator gave is explained
      Given the administrator of Mia's organization never gave the assistant the permission to change files
      When Mia asks her assistant to move "Plan.docx" into the folder "Archive"
      Then the assistant tells Mia that an administrator of Microsoft 365 must give the permission, and that she must sign in again after that
      And nothing is moved
