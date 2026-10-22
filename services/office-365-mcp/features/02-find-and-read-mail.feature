@outlook-mail
Feature: Finding and reading mail
  Mia receives far more mail than she can read.
  Mia asks her assistant to find messages, to read one in full with its attachments, and to follow a whole conversation.
  The assistant reads Mia's own mailbox, and a shared mailbox when Mia has access to it.

  Rule: The assistant finds a message from what Mia remembers about it

    @uc-02-01
    Scenario: Unread mail since yesterday is listed
      Given Mia received 6 messages since yesterday morning, and 2 of them are unread
      When Mia asks her assistant which messages since yesterday are unread
      Then the assistant lists the 2 unread messages
      But it does not list the 4 messages that Mia read

    @uc-02-02
    Scenario: A message is found by sender, subject, and attachment together
      Given Brightway sent "March invoice" with a PDF, and sent "March invoice reminder" with no attachment
      When Mia asks her assistant for the March invoice from Brightway that has a PDF
      Then the assistant shows "March invoice"
      But it does not show "March invoice reminder"

    @uc-02-03
    Scenario: A time window narrows the result
      Given Anna sent Mia one message in February, one in March, and one in April
      When Mia asks her assistant for the messages that Anna sent in March
      Then the assistant shows only the March message

    @uc-02-04
    Scenario: Flagged mail is listed
      Given Mia flagged 2 messages for follow-up and did not flag 5 others
      When Mia asks her assistant which messages she flagged
      Then the assistant lists the 2 flagged messages

    @uc-02-05
    Scenario: A result that may be incomplete says so
      Given 1,500 messages mention "invoice", which is more than one search returns
      When Mia asks her assistant for every message that mentions "invoice"
      Then the assistant shows the messages that the search returns
      And it tells Mia that more matching messages may exist

  Rule: The assistant reads a message and its attachments

    @uc-02-06
    Scenario: A message is read in full and its attachments are named
      Given Anna sent "Contract draft" with the attachment "Draft v2.docx" of 80 KB
      When Mia asks her assistant to read "Contract draft"
      Then the assistant gives the full text of the message
      And it names "Draft v2.docx" with its size

    @known-gap @uc-02-07
    Scenario: The content of an attachment answers a question
      Given Anna attached a 2 MB Excel workbook with a total of 4,200 in its last row
      When Mia asks her assistant for the total in the last row of that workbook
      Then the assistant answers 4,200

    @uc-02-08
    Scenario: An attachment above 10 MB is refused
      Given Anna attached a 12 MB PDF
      When Mia asks her assistant to read that PDF
      Then the assistant tells Mia that the attachment is too large to read
      And it tells Mia to open the message in Outlook

  Rule: The assistant follows a conversation from first message to last

    @uc-02-09
    Scenario: A decision is found in a long conversation
      Given a conversation of 5 messages between Mia, Anna, and Tom ends with a long message that gives a decision to launch on 14 June near its end
      When Mia asks her assistant what the conversation decided
      Then the assistant answers that the launch is on 14 June

  Rule: A shared mailbox is read only with Mia's access

    @uc-02-10
    Scenario: Unread mail of a shared mailbox is listed
      Given Mia has access to the shared mailbox "support@acme.example", which holds 3 unread messages
      When Mia asks her assistant for the unread messages in "support@acme.example"
      Then the assistant lists the 3 unread messages of "support@acme.example"
      But it does not list messages of Mia's own mailbox

    @known-gap @uc-02-11
    Scenario: A mailbox without access is refused
      Given Mia has no access to the shared mailbox "finance"
      When Mia asks her assistant for the unread messages in "finance"
      Then the assistant tells Mia that she has no access to "finance"
