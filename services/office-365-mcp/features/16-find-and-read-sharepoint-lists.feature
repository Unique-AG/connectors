@sharepoint
Feature: Finding and reading SharePoint lists
  Mia's team tracks tasks and issues in lists on SharePoint sites.
  Mia asks her assistant which lists a site has, which columns a list has, and which items a list holds.
  The assistant sees only the lists that Mia herself can open.

  Background:
    Given Mia can open the Finance site

  Rule: The assistant finds the lists of a site that Mia names

    @happy @uc-16-01
    Scenario: The lists of a site are shown
      Given the Finance site holds the lists "Tasks" and "Issues", a hidden list, and the library "Documents"
      When Mia asks her assistant which lists the Finance site has
      Then the assistant names the lists "Tasks" and "Issues"
      But it does not name the hidden list or the library "Documents"

    @unhappy @uc-16-02
    Scenario: A site name is not taken for the address of a site
      Given Mia has not given the web address of the Finance site
      When Mia asks her assistant which lists the site "Finance" has
      Then the assistant finds the web address of the Finance site before it names a list
      But it does not name a list of another site

  Rule: The assistant describes the columns of a list

    @happy @uc-16-03
    Scenario: The columns of a list are shown
      Given the list "Tasks" has the required column "Title" and the column "Status" with the choices "Open" and "Closed"
      When Mia asks her assistant which columns the list "Tasks" has
      Then the assistant names the columns "Title" and "Status"
      And it says that "Status" takes "Open" or "Closed"

    @unhappy @uc-16-04
    Scenario: A folder is not taken for a list
      Given Mia's OneDrive holds a folder "Tasks", and the Finance site holds the list "Tasks"
      When Mia asks her assistant which columns the list "Tasks" on the Finance site has
      Then the assistant names the columns of the list "Tasks" on the Finance site
      But it does not describe the folder "Tasks" as a list

  Rule: The assistant reads the items of a list

    @happy @uc-16-05
    Scenario: The open items of a list are shown
      Given the list "Tasks" holds the open item "Close books" with the amount 12.5
      When Mia asks her assistant for the open items of the list "Tasks"
      Then the assistant names the item "Close books" with the amount 12.5
      And it gives the web address that opens the item in a browser

    @unhappy @uc-16-06
    Scenario: A filter on a column that the list does not index is refused
      Given the column "Notes" of the list "Tasks" is not indexed
      When Mia asks her assistant for the items of the list "Tasks" whose notes say "q1"
      Then the assistant tells Mia that it can filter only on an indexed column
      But it does not present other items as the items that match

