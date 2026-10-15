@outlook-mail
Feature: Mailbox preferences
  Mia sets how her mailbox behaves while she is away and which senders reach her attention first.

  Rule: An automatic reply always has an end

    Scenario: An automatic reply runs for a fixed period
      When Mia asks her assistant to turn on her out-of-office reply from Monday to Friday with a short message
      Then Mia is asked to approve the reply first
      And after she approves, senders receive the message from Monday to Friday
      But no sender receives it on the Saturday after

    Scenario: An automatic reply without an end date is refused
      When Mia asks her assistant to turn on her out-of-office reply with no end date
      Then the assistant asks Mia for the last day of the reply
      And the reply stays off

    Scenario: An automatic reply is turned off
      Given Mia's out-of-office reply is on
      When Mia asks her assistant to turn it off
      Then senders receive no automatic reply

  Rule: A sender has a fixed tab in the inbox

    Scenario: Mail from one sender always lands in Focused
      Given Mia receives mail from the CEO in the Other tab
      When Mia asks her assistant to always put mail from the CEO in Focused
      Then new mail from the CEO arrives in the Focused tab
