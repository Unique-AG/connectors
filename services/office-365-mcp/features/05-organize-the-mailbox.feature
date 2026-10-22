@outlook-mail
Feature: Organizing the mailbox
  Mia keeps her mailbox in order with folders, categories, and inbox rules.
  Mia asks her assistant to file, mark, and sort mail in bulk, and to set up rules that do it for her later.
  The assistant erases no mail for good. A delete moves mail to Deleted Items.

  Rule: A batch is checked whole and reported for each message

    @working @uc-05-01
    Scenario: A batch is filed in one folder
      Given Mia has 8 newsletters from last month in her inbox
      When Mia asks her assistant to file them in the folder "Newsletters"
      Then all 8 newsletters are in "Newsletters"
      And her inbox holds none of them

    @working @uc-05-02
    Scenario Outline: A batch is marked in one step
      Given Mia has 8 newsletters from last month in her inbox
      When Mia asks her assistant to <action> all 8 newsletters
      Then all 8 newsletters <result>

      Examples:
        | action                           | result                       |
        | mark as read                     | are marked as read           |
        | flag for follow-up               | are flagged for follow-up    |
        | put the category "Reading" on    | carry the category "Reading" |

    @seen-failing @uc-05-03
    Scenario: A batch with one value that is not a message moves nothing
      Given Mia named 5 messages by their subjects only
      And the assistant holds a subject line in place of one of the 5 messages
      When the assistant files the 5 messages in "Archive"
      Then no message is moved
      And the next attempt names only messages that a search or a listing of her mail returned

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

    @uc-05-05
    Scenario: A change in a shared mailbox needs Mia's approval
      Given Mia has access to the shared mailbox "support@example.com"
      When Mia asks her assistant to file a message of "support@example.com" in its folder "Handled"
      Then Mia is asked to approve the change first
      And the message stays where it is until she approves

  Rule: Mia keeps her folders as she names them

    @working @uc-05-06
    Scenario: A folder is created inside another folder
      Given Mia has the folder "Projects"
      When Mia asks her assistant to create the folder "Alpha" inside "Projects"
      Then "Projects" holds the folder "Alpha"

    @working @uc-05-07
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

  Rule: A category names a kind of mail across all folders

    @working @uc-05-10
    Scenario: A new category is created and put on mail
      Given Mia has 4 unread messages from her manager
      When Mia asks her assistant to create the red category "Follow-up Q4" and put it on those messages
      Then the category "Follow-up Q4" exists and is red
      And the 4 messages carry it

  Rule: An inbox rule acts on new mail without Mia

    @working @uc-05-11
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
