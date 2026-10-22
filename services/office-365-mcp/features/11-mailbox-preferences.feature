@outlook-mail
Feature: Mailbox preferences
  Mia sets how her mailbox behaves while she is away and which senders reach her attention first.

  Rule: An automatic reply always has an end

    @uc-11-01
    Scenario: An automatic reply runs for a fixed period
      When Mia asks her assistant to turn on her out-of-office reply from Monday to Friday with a short message for all senders, and she approves it
      Then the stored reply is scheduled from Monday 00:00 to Saturday 00:00 in Mia's time zone
      And the stored reply holds the message for senders inside and outside the organization

    @uc-11-02
    Scenario: An automatic reply without an end date is refused
      When Mia asks her assistant to turn on her out-of-office reply with no end date
      Then the assistant asks Mia for the last day of the reply
      And the reply stays off

    @uc-11-03
    Scenario: An automatic reply is turned off
      Given Mia's out-of-office reply is on
      When Mia asks her assistant to turn it off
      Then senders receive no automatic reply

  Rule: Mia can see the state of her automatic reply

    @uc-11-07
    Scenario: The state of the automatic reply is read
      Given Mia's out-of-office reply is on until Friday with the message "I am away until Monday"
      When Mia asks her assistant whether her out-of-office reply is on
      Then the assistant tells Mia that the reply is on until Friday
      And it gives the message "I am away until Monday"

  Rule: An automatic reply starts only after Mia agrees
    The reply answers every sender, and nobody can recall an answer that went out.

    @uc-11-05
    Scenario: An automatic reply starts only after Mia approves it
      When Mia asks her assistant to turn on her out-of-office reply from Monday to Friday
      Then Mia is asked to approve the reply first
      And her out-of-office reply stays off until she approves

    @uc-11-06
    Scenario: A declined automatic reply stays off
      Given Mia's out-of-office reply is off
      When Mia asks her assistant to turn on her out-of-office reply from Monday to Friday, and she declines to approve it
      Then the assistant tells Mia that the reply was not turned on
      And senders receive no automatic reply

  Rule: A sender has a fixed tab in the inbox

    @uc-11-04
    Scenario: Mail from one sender always lands in Focused
      Given Mia receives mail from Ada Keller at "ada@acme.example" in the Other tab
      When Mia asks her assistant to always put mail from "ada@acme.example" in Focused
      Then the list of fixed senders holds "ada@acme.example" in the Focused tab
