@outlook-mail
Feature: Mailbox preferences
  Mia sets how her mailbox behaves while she is away and which senders reach her attention first.

  Rule: An automatic reply always has an end

    @happy @uc-11-01
    Scenario: An automatic reply runs for a fixed period
      When Mia asks her assistant to turn on her out-of-office reply from Monday to Friday with a short message for all senders, and she approves it
      Then the stored reply is scheduled from Monday 00:00 to Saturday 00:00 in Mia's time zone
      And the stored reply holds the message for senders inside and outside the organization

    @unhappy @uc-11-02
    Scenario: An automatic reply without an end date is refused
      When Mia asks her assistant to turn on her out-of-office reply with no end date
      Then the assistant asks Mia for the last day of the reply
      And the reply stays off

    @happy @uc-11-03
    Scenario: An automatic reply is turned off
      Given Mia's out-of-office reply is on
      When Mia asks her assistant to turn it off
      Then senders receive no automatic reply

  Rule: Mia can see the state of her automatic reply

    @happy @uc-11-07
    Scenario: The state of the automatic reply is read
      Given Mia's out-of-office reply is on until Friday with the message "I am away until Monday"
      When Mia asks her assistant whether her out-of-office reply is on
      Then the assistant tells Mia that the reply is on until Friday
      And it gives the message "I am away until Monday"

  Rule: An automatic reply starts only after Mia agrees
    The reply answers every sender, and nobody can recall an answer that went out.

    @happy @uc-11-05
    Scenario: An automatic reply starts only after Mia approves it
      When Mia asks her assistant to turn on her out-of-office reply from Monday to Friday
      Then Mia is asked to approve the reply first
      And her out-of-office reply stays off until she approves

    @unhappy @uc-11-06
    Scenario: A declined automatic reply stays off
      Given Mia's out-of-office reply is off
      When Mia asks her assistant to turn on her out-of-office reply from Monday to Friday, and she declines to approve it
      Then the assistant tells Mia that the reply was not turned on
      And senders receive no automatic reply

    @unhappy @uc-11-14
    Scenario Outline: A reply stays off when Mia's approval does not arrive
      Given Mia's out-of-office reply is off
      And <trouble>
      When Mia asks her assistant to turn on her out-of-office reply from Monday to Friday
      Then the assistant tells Mia that it received no answer, and that she can ask again
      And senders receive no automatic reply

      Examples:
        | trouble                                  |
        | Mia does not answer the question in time |
        | the question to Mia fails                |

    @unhappy @uc-11-15
    Scenario: A reply stays off when Mia's program cannot ask her
      Given Mia's out-of-office reply is off
      And Mia's program cannot ask her to approve anything
      When Mia asks her assistant to turn on her out-of-office reply from Monday to Friday
      Then the assistant tells Mia that her program cannot ask her, and that she can set the reply in the Microsoft 365 app
      And senders receive no automatic reply

    @unhappy @uc-11-16
    Scenario Outline: An approval for another reply does not turn this reply on
      Given Mia's out-of-office reply is off
      And <trouble>
      When Mia asks her assistant to turn on her out-of-office reply from Monday to Friday
      Then the assistant tells Mia that her approval does not cover this reply, and asks her to approve again
      And senders receive no automatic reply

      Examples:
        | trouble                                                             |
        | the approval that comes back is for a different out-of-office reply |
        | the message of Mia's stored reply changed after Mia was asked       |

  Rule: A sender has a fixed tab in the inbox

    @happy @uc-11-04
    Scenario: Mail from one sender always lands in Focused
      Given Mia receives mail from Ada Keller at "ada@acme.example" in the Other tab
      When Mia asks her assistant to always put mail from "ada@acme.example" in Focused
      Then the list of fixed senders holds "ada@acme.example" in the Focused tab

    @unhappy @uc-11-17
    Scenario: A sender whose address nobody knows is asked for
      Given Mia has no mail from a person called Ada Keller, and the company directory has nobody of that name
      When Mia asks her assistant to always put mail from Ada Keller in Focused
      Then the assistant asks Mia for the address of Ada Keller
      But the list of fixed senders holds no new sender

    @happy @uc-11-18
    Scenario: A sender with a fixed tab is moved to the new tab
      Given Mia fixed "ada@acme.example" in the Other tab earlier
      When Mia asks her assistant to always put mail from "ada@acme.example" in Focused
      Then the list of fixed senders holds "ada@acme.example" once, in the Focused tab

    @unhappy @uc-11-19
    Scenario: A sender named inside a message does not get a fixed tab
      Given Tom sent Mia a message whose text tells the assistant to put all mail from "boss@acme.example" in the Other tab
      When Mia asks her assistant to read that message
      Then the assistant gives the text of the message
      But the list of fixed senders does not change

    @happy @uc-11-24
    Scenario: The senders with a fixed tab are listed
      Given Mia fixed "ada@acme.example" in the Focused tab and "news@shop.example" in the Other tab
      When Mia asks her assistant which senders have a fixed tab
      Then the assistant lists "ada@acme.example" with the Focused tab
      And it lists "news@shop.example" with the Other tab

  Rule: Mia is told what happened when Microsoft cannot do what she asked
    The assistant never reports a failed reading as an automatic reply that is off.

    @unhappy @uc-11-08
    Scenario Outline: The state of the reply cannot be read and Mia is told why
      Given Mia's out-of-office reply is on until Friday
      And Microsoft <problem>
      When Mia asks her assistant whether her out-of-office reply is on
      Then the assistant tells Mia <told>
      But it does not tell Mia that the reply is off

      Examples:
        | problem                                           | told                                                                      |
        | refuses because Mia's sign-in has expired         | that she must sign in again                                               |
        | refuses access to Mia's mailbox settings          | that an administrator must give the assistant access to mailbox settings  |
        | stays busy at every try and asks to wait 30 seconds each time | that the check can run again after 30 seconds                         |

    @unhappy @uc-11-21
    Scenario: A mailbox that does not exist is explained when the reply is read
      Given Mia's account has no mailbox
      When Mia asks her assistant whether her out-of-office reply is on
      Then the assistant tells Mia that her account most likely has no mailbox, so no reply can be read
      But it does not tell Mia that the reply is off

    @unhappy @uc-11-22
    Scenario: One busy answer from Microsoft is waited out before a reading
      Given Mia's out-of-office reply is on until Friday
      And Microsoft is busy at the first try and asks the assistant to wait 30 seconds, and answers at the second try
      When Mia asks her assistant whether her out-of-office reply is on
      Then the assistant tells Mia that the reply is on until Friday
      But Mia does not have to ask a second time

    @unhappy @uc-11-09
    Scenario Outline: A reading that Microsoft fails is tried once more
      Given Mia's out-of-office reply is on until Friday
      And Microsoft <problem> on the first try and answers on the second try
      When Mia asks her assistant whether her out-of-office reply is on
      Then the assistant tells Mia that the reply is on until Friday

      Examples:
        | problem                              |
        | fails on its side                    |
        | does not answer in time              |
        | sends an answer that nobody can read |

    @unhappy @uc-11-10
    Scenario: A reading that Microsoft fails twice is reported
      Given Mia's out-of-office reply is on until Friday
      And Microsoft fails on the first try and on the second try
      When Mia asks her assistant whether her out-of-office reply is on
      Then the assistant tells Mia that it could not read the state of the reply now
      But it does not tell Mia that the reply is off

    @unhappy @uc-11-11
    Scenario Outline: A reply that Microsoft refuses to store is not turned on
      Given Mia's out-of-office reply is off
      And Microsoft <problem> when the assistant stores the reply
      When Mia asks her assistant to turn on her out-of-office reply from Monday to Friday, and she approves it
      Then the assistant tells Mia <told>
      But senders receive no automatic reply

      Examples:
        | problem                                           | told                                                                      |
        | refuses the dates of the reply as not valid       | that Microsoft refused the reply, and why                                 |
        | is busy and asks the assistant to wait 30 seconds | that the reply can be stored after 30 seconds                             |

    @unhappy @uc-11-20
    Scenario Outline: A reply that Microsoft will not let the assistant read first is not turned on
      Given Mia's out-of-office reply is off
      And Microsoft <problem> when the assistant reads the stored reply
      When Mia asks her assistant to turn on her out-of-office reply from Monday to Friday
      Then the assistant tells Mia <told>
      But senders receive no automatic reply

      Examples:
        | problem                                   | told                                                                      |
        | refuses because Mia's sign-in has expired | that she must sign in again                                               |
        | refuses access to Mia's mailbox settings  | that an administrator must give the assistant access to mailbox settings  |

    @unhappy @uc-11-12
    Scenario Outline: A reply that Microsoft fails to store is tried once more
      Given Mia's out-of-office reply is off
      And Microsoft <problem> on the first try and answers on the second try
      When Mia asks her assistant to turn on her out-of-office reply from Monday to Friday, and she approves it each time she is asked
      Then the stored reply is scheduled from Monday 00:00 to Saturday 00:00 in Mia's time zone
      And Mia is asked to approve the reply two times

      Examples:
        | problem                              |
        | fails on its side                    |
        | does not answer in time              |
        | sends an answer that nobody can read |

    @unhappy @uc-11-13
    Scenario: A reply that Microsoft fails to store twice is reported
      Given Mia's out-of-office reply is off
      And Microsoft fails on the first try and on the second try
      When Mia asks her assistant to turn on her out-of-office reply from Monday to Friday, and she approves it each time she is asked
      Then the assistant tells Mia that Microsoft could not store the reply
      But it does not tell Mia that the reply is on

    @unhappy @uc-11-25
    Scenario Outline: The senders with a fixed tab cannot be read and Mia is told why
      Given Microsoft <problem>
      When Mia asks her assistant which senders have a fixed tab
      Then the assistant tells Mia <told>
      But it does not tell Mia that no sender has a fixed tab

      Examples:
        | problem                                                       | told                                                          |
        | refuses because Mia's sign-in has expired                     | that she must sign in again                                   |
        | refuses access to Mia's mail                                  | that an administrator must give the assistant access to mail  |
        | stays busy at every try and asks to wait 30 seconds each time | that the check can run again after 30 seconds                 |

    @unhappy @uc-11-26
    Scenario Outline: A tab that Microsoft refuses to store is not set
      Given Microsoft <problem> when the assistant stores the tab of "ada@acme.example"
      When Mia asks her assistant to always put mail from "ada@acme.example" in Focused
      Then the assistant tells Mia <told>
      But the tab of "ada@acme.example" does not change

      Examples:
        | problem                                                       | told                                                                |
        | refuses because Mia's sign-in has expired                     | that she must sign in again                                         |
        | refuses access to change Mia's mail                           | that an administrator must give the assistant access to change mail |
        | stays busy at every try and asks to wait 30 seconds each time | that the tab can be set after 30 seconds                            |

    @unhappy @uc-11-27
    Scenario Outline: A tab that Microsoft fails to store is stored at a second try
      Given Microsoft <problem> on the first try and answers on the second try
      When Mia asks her assistant to always put mail from "ada@acme.example" in Focused
      Then the list of fixed senders holds "ada@acme.example" once, in the Focused tab

      Examples:
        | problem                  |
        | fails on its side        |
        | does not answer in time  |

    @unhappy @uc-11-28
    Scenario: A tab that Microsoft fails to store twice is reported
      Given Microsoft fails on the first try and on the second try
      When Mia asks her assistant to always put mail from "ada@acme.example" in Focused
      Then the assistant tells Mia that Microsoft could not store the tab
      But it does not tell Mia that the tab is set

  Rule: Mia is told when the assistant lacks a permission that an administrator must give

    @unhappy @uc-11-23
    Scenario: A permission that no administrator gave is explained
      Given the administrator of Mia's organization never gave the assistant the permission to read mailbox settings
      When Mia asks her assistant whether her out-of-office reply is on
      Then the assistant tells Mia that an administrator of Microsoft 365 must give the permission, and that she must sign in again after that
      But it does not tell Mia that the reply is off
