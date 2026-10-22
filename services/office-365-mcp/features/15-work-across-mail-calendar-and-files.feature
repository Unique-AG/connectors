@outlook-mail @outlook-calendar @sharepoint @teams
Feature: Working across mail, calendar, files, and Teams
  Mia's work does not stay in one application. A message leads to a meeting, a meeting leads to a document, and a chat leads to a mail.
  Mia asks her assistant for one answer that needs more than one source.
  The assistant uses only what Mia herself can see in her mailbox, her calendar, her files, and her chats.

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

  Rule: Mia prepares for a meeting from the invitation, the mail, and the files

    @uc-15-05
    Scenario: A meeting is prepared from its invitation, mail, and files
      Given Mia has "Launch review" tomorrow with Anna and Tom
      And Anna wrote Mia a mail about "Launch review" yesterday
      And the mail of Anna names the deck "Launch Plan.pptx", which is in the Sales site
      When Mia asks her assistant to prepare her for "Launch review"
      Then the assistant gives the time and the attendees of "Launch review"
      And it summarizes the mail of Anna
      And it names the deck "Launch Plan.pptx"

  Rule: Mia gathers what she has on one customer from three places

    @uc-15-07
    Scenario: Mail, Teams messages, and files about a customer are gathered
      Given Acme wrote to Mia by mail about the renewal
      And Tom wrote about Acme in a Teams chat
      And the Sales site holds the file "Acme Proposal.docx"
      When Mia asks her assistant for everything about Acme
      Then the assistant names the mail from Acme
      And it names the message of Tom
      And it names "Acme Proposal.docx"

  Rule: A Teams discussion or a meeting leads to a mail

    @uc-15-06
    Scenario: A decision from a chat becomes a mail draft
      Given Anna and Tom agreed in the chat "Launch" that the launch moves to 14 June
      When Mia asks her assistant to draft a mail to Anna and Tom that states the decision
      Then the draft to Anna and Tom states that the launch moves to 14 June
      And the draft is not sent

    @uc-15-09
    Scenario: The action items of a meeting go into a mail draft for its attendees
      Given "Design review" of yesterday has a transcript with 3 action items
      And Anna and Tom attended it
      When Mia asks her assistant to draft a mail to the attendees with the action items
      Then the draft to Anna and Tom lists the 3 action items
      And the draft is not sent

  Rule: A file moves between mail, Teams, and SharePoint

    @uc-15-10
    Scenario: A file is sent to a colleague as a link in a mail draft
      Given the latest price list is in the Sales site
      When Mia asks her assistant to send the price list to Anna by mail
      Then Mia is asked to approve a sharing link first
      And after she approves, the draft to Anna holds a link that opens the price list
      And the draft is not sent

    @uc-15-11
    Scenario: The text of a mail is saved as a file in a folder
      Given Anna wrote the mail "Offer terms", and the folder "Offers" is in the Sales site
      When Mia asks her assistant to save the text of Anna's mail in "Offers"
      Then Mia is asked to approve the new file first
      And after she approves, "Offers" holds a text file with the text of the mail

    @uc-15-12
    Scenario: A file that Anna posted in Teams is read
      Given Anna posted the file "Offer.docx" in a chat with Mia yesterday
      When Mia asks her assistant what is in the file that Anna posted
      Then the assistant tells Mia the main terms of "Offer.docx"
