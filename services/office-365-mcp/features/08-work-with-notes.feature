@onenote
Feature: Working with notes in OneNote
  Mia keeps her notes in OneNote notebooks, and her team keeps shared notebooks.
  Mia asks her assistant to find a note, to read it, to capture new notes, and to change a note.
  A change in a notebook of a team or a site needs Mia's approval first.

  Rule: The assistant finds a note by its title and not by its content

    @uc-08-01
    Scenario: A page is found by a word in its title
      Given Mia has the page "Acme kickoff" in the notebook "Customers"
      When Mia asks her assistant for her notes from the Acme kickoff
      Then the assistant shows the page "Acme kickoff"

    @known-gap @uc-08-02
    Scenario: A page is found by a word that is only in its body
      Given Mia has the page "Kickoff" that mentions "Zephyr" only in its body
      When Mia asks her assistant for the notes that mention "Zephyr"
      Then the assistant shows the page "Kickoff"

    @uc-08-03
    Scenario: A notebook is opened from a web address
      Given Anna sent Mia the web address of the notebook "Customers"
      When Mia asks her assistant for the sections of that notebook
      Then the assistant lists the sections of "Customers"

  Rule: The assistant captures and changes notes

    @uc-08-04
    Scenario: New notes become a page in a section
      Given Mia has the section "Work" in her notebook "Customers"
      When Mia asks her assistant to create the page "Weekly sync" with three notes in "Work"
      Then the section "Work" holds the page "Weekly sync"
      And the page holds the three notes in order

    @uc-08-05
    Scenario: A task list is added to the end of an existing page
      Given Mia has the page "Planning" with 2 paragraphs
      When Mia asks her assistant to add a task list at the end of "Planning"
      Then "Planning" ends with the task list
      But its 2 paragraphs are unchanged

    @uc-08-06
    Scenario: A sentence is changed in place
      Given the page "Planning" states "Launch on 14 June" in its second paragraph
      When Mia asks her assistant to change that date to 21 June
      Then Mia is asked to approve the change first
      And after she approves, the second paragraph states "Launch on 21 June"
      But the other paragraphs are unchanged

    @uc-08-07
    Scenario: A page is erased only after Mia approves
      Given Mia has the page "Old draft"
      When Mia asks her assistant to erase "Old draft"
      Then Mia is asked to approve the erase first
      And the assistant tells Mia that OneNote keeps no copy of an erased page

  Rule: A change in a team notebook needs Mia's approval

    @uc-08-08
    Scenario: A page is added to the notebook of a team
      Given Mia belongs to the team "Platform", which owns a notebook
      When Mia asks her assistant to add the page "Retro" to the notebook of "Platform"
      Then Mia is asked to approve the change first
      And after she approves, the notebook of "Platform" holds "Retro"
