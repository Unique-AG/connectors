@outlook-mail
Feature: Organizing the mailbox
  Mia keeps her mailbox in order with folders, categories, and inbox rules.
  Mia asks her assistant to file, mark, and sort mail in bulk, and to set up rules that do it for her later.
  The assistant erases no mail for good. A delete moves mail to Deleted Items.

  Rule: A batch is checked whole and reported for each message

    @uc-05-01
    Scenario: A batch is filed in one folder
      Given Mia has 8 newsletters from last month in her inbox
      When Mia asks her assistant to file them in the folder "Newsletters"
      Then all 8 newsletters are in "Newsletters"
      And her inbox holds none of them

    @uc-05-02
    Scenario Outline: A batch is marked in one step
      Given Mia has 8 newsletters from last month in her inbox
      When Mia asks her assistant to <action> all 8 newsletters
      Then all 8 newsletters <result>

      Examples:
        | action                           | result                       |
        | mark as read                     | are marked as read           |
        | flag for follow-up               | are flagged for follow-up    |
        | put the category "Reading" on    | carry the category "Reading" |

    @uc-05-19
    Scenario: A flag carries a due date
      Given Mia has 3 messages from Tom in her inbox
      When Mia asks her assistant to flag them for follow-up by Friday
      Then the 3 messages are flagged for follow-up
      And each flag is due on Friday

    @uc-05-03
    Scenario: Messages that Mia names by subject are found again and filed
      Given Mia named 5 messages by their subjects only
      When Mia asks her assistant to file the 5 messages in "Archive"
      Then the assistant finds the 5 messages in her mailbox
      And all 5 messages are in "Archive"

    @uc-05-16
    Scenario: A batch with one missing message moves the others
      Given Mia asks her assistant to file 5 messages in "Archive"
      And one of the 5 messages is gone from her mailbox
      When the assistant files the 5 messages
      Then 4 messages are in "Archive"
      And the assistant tells Mia which message failed

    @uc-05-04
    Scenario: A delete moves mail to Deleted Items
      Given Mia has 3 old messages from a vendor
      When Mia asks her assistant to delete them
      Then the 3 messages are in Deleted Items
      But none of them is erased for good

    @uc-05-17
    Scenario: A batch is archived
      Given Mia has 6 messages from last month in her inbox
      When Mia asks her assistant to archive them
      Then all 6 messages are in her archive
      And her inbox holds none of them

    @uc-05-18
    Scenario: A message is kept in a second folder
      Given Mia has the message "Signed contract" in her inbox
      When Mia asks her assistant to keep a copy of it in the folder "Contracts"
      Then the folder "Contracts" holds a copy of "Signed contract"
      And the original is still in her inbox

    @uc-05-05
    Scenario: A change in a shared mailbox needs Mia's approval
      Given Mia has access to the shared mailbox "support@example.com"
      And that mailbox holds the message "Refund question"
      When Mia asks her assistant to file the message "Refund question" of "support@example.com" in its folder "Handled"
      Then Mia is asked to approve the change first
      And the message stays where it is until she approves

  Rule: Mia keeps her folders as she names them

    @uc-05-06
    Scenario: A folder is created inside another folder
      Given Mia has the folder "Projects"
      When Mia asks her assistant to create the folder "Alpha" inside "Projects"
      Then "Projects" holds the folder "Alpha"

    @uc-05-07
    Scenario: A folder is renamed and keeps its mail
      Given the folder "Old" holds 40 messages
      When Mia asks her assistant to rename "Old" to "Archive 2025"
      Then the folder "Archive 2025" holds the 40 messages

    @uc-05-08
    Scenario: A folder moves to Deleted Items only after Mia approves
      Given the folder "Temp" holds 5 messages and a subfolder
      When Mia asks her assistant to delete "Temp"
      Then Mia is asked to approve the delete first
      And after she approves, "Temp" with all of its content is in Deleted Items

    @uc-05-09
    Scenario: A built-in folder is never renamed or deleted
      When Mia asks her assistant to delete the folder "Inbox"
      Then the assistant tells Mia that Outlook keeps "Inbox" for every mailbox
      And the folder "Inbox" is unchanged

    @uc-05-20
    Scenario: Two folders with one name lead to a question
      Given Mia has a folder "Finance" inside her inbox
      And Mia has a folder "Finance" inside her archive
      When Mia asks her assistant to file 3 invoices in the folder "Finance"
      Then the assistant asks Mia which folder "Finance" she means
      But no invoice is moved yet

  Rule: Deleted mail stays in Deleted Items
    The assistant cannot erase mail for good, so Mia empties Deleted Items herself.

    @uc-05-21
    Scenario: Deleted Items is emptied only by Mia
      Given Deleted Items holds 120 messages
      When Mia asks her assistant to empty Deleted Items
      Then the assistant tells Mia to empty Deleted Items in Outlook
      But Deleted Items still holds the 120 messages

  Rule: A category names a kind of mail across all folders

    @uc-05-10
    Scenario: A new category is created and put on mail
      Given Mia has 4 unread messages from Tom Berger
      When Mia asks her assistant to create the red category "Follow-up Q4" and put it on those messages
      Then the category "Follow-up Q4" exists and is red
      And the 4 messages carry it

    @uc-05-22
    Scenario: A category is renamed
      Given Mia has the category "Follow-up Q4" on 4 messages
      When Mia asks her assistant to rename the category to "Follow-up Q1"
      Then Mia's categories hold "Follow-up Q1"
      And the 4 messages carry "Follow-up Q1"

  Rule: An inbox rule acts on new mail without Mia

    @uc-05-11
    Scenario: A rule files mail from one sender
      When Mia asks her assistant for a rule that moves mail from "billing@example.com" to "Finance"
      Then Mia's rules include a rule with that sender and that folder
      And new mail from "billing@example.com" arrives in "Finance"

    @uc-05-12
    Scenario: An old rule is turned off and stays in the list
      Given Mia has the rule "Receipts"
      When Mia asks her assistant to turn off "Receipts"
      Then "Receipts" is still in Mia's rules
      But it no longer acts on new mail

    @uc-05-13
    Scenario: A rule that forwards mail needs approval that names every address
      When Mia asks her assistant for a rule that forwards mail from "ceo@example.com" to "anna@example.com" and "tom@example.com"
      Then Mia is asked to approve the rule first
      And the question names "anna@example.com" and "tom@example.com"

    @uc-05-14
    Scenario: A rule is erased only after Mia approves
      Given Mia has the rule "Receipts"
      When Mia asks her assistant to erase "Receipts"
      Then Mia is asked to approve the erase first
      And after she approves, "Receipts" is no longer in her rules

    @uc-05-15
    Scenario: A rule never erases mail for good
      When Mia asks her assistant for a rule that deletes mail from "spam@example.com"
      Then new mail from "spam@example.com" arrives in Deleted Items
      But none of it is erased for good

    @uc-05-23
    Scenario: A rule without a clear condition is checked with Mia first
      When Mia asks her assistant for a rule that moves the mail she does not need to "Archive"
      Then the assistant asks Mia which mail the rule is for
      And the assistant tells Mia that a rule without a condition acts on every new message
      But no rule exists until Mia names the mail or agrees

    @uc-05-24
    Scenario: A rule is narrowed
      Given Mia has the rule "Billing to Finance" that moves mail from "billing@example.com"
      When Mia asks her assistant to make the rule act only on mail with "invoice" in the subject
      Then the rule "Billing to Finance" needs both the sender and the word "invoice"
      And Mia's rules hold no second rule with that name

    @uc-05-25
    Scenario: A rule that is off is turned on again
      Given Mia has the rule "Receipts" turned off
      When Mia asks her assistant to turn "Receipts" on again
      Then "Receipts" acts on new mail again
      And Mia's rules hold no second rule named "Receipts"
