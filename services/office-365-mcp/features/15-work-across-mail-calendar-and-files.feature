@outlook-mail @outlook-calendar @sharepoint
Feature: Working across mail, calendar, and files
  Mia's work does not stay in one application. A message leads to a meeting, and a meeting leads to a document.
  Mia asks her assistant for one answer that needs more than one source.
  The assistant uses only what Mia herself can see in her mailbox, her calendar, and her files.

  Rule: Mia starts her day with one overview

    @uc-15-01
    Scenario: A morning brief joins meetings and mail
      Given Mia has 3 meetings today and 12 unread messages, 2 of them from Anna
      And Mia named Anna as the person whose mail comes first
      When Mia asks her assistant for a brief of her day
      Then the assistant lists the 3 meetings with their attendees
      And it names the 2 messages of Anna first among the unread mail

  Rule: Mia goes through her inbox in one sitting

    @uc-15-02
    Scenario: A meeting invitation is shown and not answered without Mia
      Given Mia's inbox holds 9 newsletters and one meeting invitation from Anna
      When Mia asks her assistant to go through her inbox
      Then the assistant shows the invitation of Anna
      And it asks Mia how to answer the invitation
      But it does not answer the invitation

    @uc-15-03
    Scenario: A reply uses a document from SharePoint
      Given Anna asked Mia by mail for the latest price list
      And the latest price list is in the Sales site
      When Mia asks her assistant to answer Anna with the latest price list
      Then the draft to Anna quotes the prices of the latest price list
      And the draft is not sent

    @uc-15-04
    Scenario: A thread leads to a time for a workshop
      Given Anna and Tom discussed a workshop of 90 minutes in a thread of 8 messages
      And they need a time next week
      When Mia asks her assistant to find a time for the workshop that the thread describes
      Then the assistant names times next week when Mia, Anna, and Tom are free
