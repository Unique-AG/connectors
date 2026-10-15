@outlook-contacts
Feature: Managing contacts
  Mia keeps the people she works with in her Outlook contacts.
  Mia asks her assistant to look up a person, to save a new contact, and to add a detail to a contact.

  Rule: The assistant answers from Mia's contacts

    Scenario: A phone number is found in a contact
      Given Mia has the contact Anna Meier with the telephone number "+41 44 555 01 01"
      When Mia asks her assistant for the telephone number of Anna Meier
      Then the assistant answers "+41 44 555 01 01"

    @known-gap
    Scenario: A person who is only in the company directory is found
      Given Tom Berger is in the company directory and not in Mia's contacts
      When Mia asks her assistant for the telephone number of Tom Berger
      Then the assistant answers with the telephone number of Tom Berger from the directory

  Rule: A change to a contact keeps what it already holds

    Scenario: A new contact is saved
      When Mia asks her assistant to save Tom Berger of Acme with the address "tom@acme.example" as a contact
      Then Mia's contacts hold one contact Tom Berger with the company "Acme" and that address

    Scenario: A second telephone number is added next to the first
      Given Mia has the contact Tom Berger with the mobile number "+41 79 555 01 02"
      When Mia asks her assistant to add the office number "+41 44 555 01 03" to Tom Berger
      Then the contact Tom Berger holds both numbers
