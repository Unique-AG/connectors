@outlook-mail
Feature: Drafting and sending mail
  Mia lets her assistant write mail for her.
  The assistant leaves each message as a draft for Mia to read, and sends it only after Mia approves.

  Rule: A draft goes to the real address of the right person

    @uc-04-01
    Scenario: A draft is addressed to the address of the named person
      Given Anna Meier works in Legal and has the address "anna.meier@example.com"
      When Mia asks her assistant to draft a note to Anna Meier that asks for the contract by Friday
      Then the draft is addressed to "anna.meier@example.com"
      And the draft asks for the contract by Friday

    @uc-04-02
    Scenario: Two people with one name lead to a question
      Given Anna Meier in Legal has the address "anna.meier@example.com"
      And Anna Meier in Sales has the address "anna.meier.sales@example.com"
      When Mia asks her assistant to draft a note to Anna Meier
      Then the assistant asks Mia which Anna Meier she means
      But it does not create the draft yet

    @uc-04-03
    Scenario: Mia asks whether Anna is away
      Given Anna works in Mia's organization and has an automatic reply turned on
      When Mia asks her assistant whether Anna is away
      Then the assistant tells Mia the text of the automatic reply of Anna

  Rule: A draft changes until Mia approves it

    @uc-04-04
    Scenario: A draft is shortened in place
      Given Mia has a draft to Anna with 4 paragraphs
      When Mia asks her assistant to make the draft shorter
      Then the same draft has fewer words
      And the shorter text still names the same facts
      But Mia's mailbox holds no second draft

    @uc-04-05
    Scenario: A person is not both addressed and copied
      Given Mia has a draft addressed to Tom
      When Mia asks her assistant to copy Tom on the draft as well
      Then the assistant tells Mia that Tom is already on the draft
      But the draft stays as it is until Mia chooses

  Rule: Nothing is sent without Mia's approval

    @uc-04-06
    Scenario: An approved draft is sent
      Given Mia read her draft to Anna
      When Mia approves that the draft is sent
      Then the message is in Mia's sent items
      And Anna receives it once

    @uc-04-07
    Scenario: A declined draft stays a draft
      Given Mia read her draft to Anna
      When Mia declines that the draft is sent
      Then Anna receives nothing
      And the draft is still in Mia's drafts

    @uc-04-08
    Scenario: A draft that changed after the question is not sent
      Given Mia was asked to approve a draft to Anna
      And the text of the draft changed after that question
      When Mia approves
      Then Anna receives nothing
      And the assistant tells Mia that the draft changed

    @uc-04-12
    Scenario: Mia is warned about an automatic reply before a send
      Given Mia has a draft addressed to Anna
      And Anna works in Mia's organization and has an automatic reply turned on
      When Mia asks her assistant to send the draft
      Then the assistant tells Mia about the automatic reply of Anna
      And Mia is asked to approve that the draft is sent

  Rule: A reply keeps the conversation

    @uc-04-09
    Scenario: A reply to everyone lists every other person
      Given Anna wrote to Mia, Tom, and Priya
      When Mia asks her assistant for a reply to everyone
      Then the draft is addressed to Anna, Tom, and Priya
      But it is not addressed to Mia

    @uc-04-10
    Scenario: A forward carries the original attachments
      Given Anna sent Mia "Contract draft" with the attachment "Draft v2.docx"
      When Mia asks her assistant to forward "Contract draft" to Tom with a short note
      Then the draft to Tom holds "Draft v2.docx"

    @uc-04-11
    Scenario: A new file is attached to a draft
      Given Mia has "Report.pdf" in her OneDrive
      When Mia asks her assistant to mail "Report.pdf" to Anna as an attachment
      Then the message to Anna holds "Report.pdf" as an attachment
