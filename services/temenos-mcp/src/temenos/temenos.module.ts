import { Module } from '@nestjs/common';
import { TemenosConfig, temenosConfig } from '~/config';
import { Metrics, MetricsModule } from './metrics';
import { TemenosHttpClient } from './temenos-http.client';
import { GetDerivativeOptionAssignsQuery } from './tools/holdings/get-derivative-option-assigns/get-derivative-option-assigns.query';
import { GetDerivativeOptionAssignsTool } from './tools/holdings/get-derivative-option-assigns/get-derivative-option-assigns.tool';
import { GetDerivativeOptionExercisesQuery } from './tools/holdings/get-derivative-option-exercises/get-derivative-option-exercises.query';
import { GetDerivativeOptionExercisesTool } from './tools/holdings/get-derivative-option-exercises/get-derivative-option-exercises.tool';
import { GetDerivativeOptionExpiresQuery } from './tools/holdings/get-derivative-option-expires/get-derivative-option-expires.query';
import { GetDerivativeOptionExpiresTool } from './tools/holdings/get-derivative-option-expires/get-derivative-option-expires.tool';
import { GetExpiringLimitsQuery } from './tools/holdings/get-expiring-limits/get-expiring-limits.query';
import { GetExpiringLimitsTool } from './tools/holdings/get-expiring-limits/get-expiring-limits.tool';
import { GetGuaranteesQuery } from './tools/holdings/get-guarantees/get-guarantees.query';
import { GetGuaranteesTool } from './tools/holdings/get-guarantees/get-guarantees.tool';
import { GetLetterOfCreditIncoTermsQuery } from './tools/holdings/get-letter-of-credit-inco-terms/get-letter-of-credit-inco-terms.query';
import { GetLetterOfCreditIncoTermsTool } from './tools/holdings/get-letter-of-credit-inco-terms/get-letter-of-credit-inco-terms.tool';
import { GetLetterOfCreditTenorsQuery } from './tools/holdings/get-letter-of-credit-tenors/get-letter-of-credit-tenors.query';
import { GetLetterOfCreditTenorsTool } from './tools/holdings/get-letter-of-credit-tenors/get-letter-of-credit-tenors.tool';
import { GetLimitMasterGroupsQuery } from './tools/holdings/get-limit-master-groups/get-limit-master-groups.query';
import { GetLimitMasterGroupsTool } from './tools/holdings/get-limit-master-groups/get-limit-master-groups.tool';
import { GetNostroAccountsQuery } from './tools/holdings/get-nostro-accounts/get-nostro-accounts.query';
import { GetNostroAccountsTool } from './tools/holdings/get-nostro-accounts/get-nostro-accounts.tool';
import { GetPaymentStopsQuery } from './tools/holdings/get-payment-stops/get-payment-stops.query';
import { GetPaymentStopsTool } from './tools/holdings/get-payment-stops/get-payment-stops.tool';
import { GetRepoPositionMovementsQuery } from './tools/holdings/get-repo-position-movements/get-repo-position-movements.query';
import { GetRepoPositionMovementsTool } from './tools/holdings/get-repo-position-movements/get-repo-position-movements.tool';
import { GetRepoPositionsQuery } from './tools/holdings/get-repo-positions/get-repo-positions.query';
import { GetRepoPositionsTool } from './tools/holdings/get-repo-positions/get-repo-positions.tool';
import { GetReverseRepoPositionMovementsQuery } from './tools/holdings/get-reverse-repo-position-movements/get-reverse-repo-position-movements.query';
import { GetReverseRepoPositionMovementsTool } from './tools/holdings/get-reverse-repo-position-movements/get-reverse-repo-position-movements.tool';
import { GetReverseRepoPositionsQuery } from './tools/holdings/get-reverse-repo-positions/get-reverse-repo-positions.query';
import { GetReverseRepoPositionsTool } from './tools/holdings/get-reverse-repo-positions/get-reverse-repo-positions.tool';
import { GetReviewLimitsQuery } from './tools/holdings/get-review-limits/get-review-limits.query';
import { GetReviewLimitsTool } from './tools/holdings/get-review-limits/get-review-limits.tool';
import { GetSharedLimitsQuery } from './tools/holdings/get-shared-limits/get-shared-limits.query';
import { GetSharedLimitsTool } from './tools/holdings/get-shared-limits/get-shared-limits.tool';
import { GetVostroAccountsQuery } from './tools/holdings/get-vostro-accounts/get-vostro-accounts.query';
import { GetVostroAccountsTool } from './tools/holdings/get-vostro-accounts/get-vostro-accounts.tool';
import { GetPaymentFeesQuery } from './tools/order/get-payment-fees/get-payment-fees.query';
import { GetPaymentFeesTool } from './tools/order/get-payment-fees/get-payment-fees.tool';
import { GetPendingPaymentsQuery } from './tools/order/get-pending-payments/get-pending-payments.query';
import { GetPendingPaymentsTool } from './tools/order/get-pending-payments/get-pending-payments.tool';
import { GetTransactionStopInvestigationsQuery } from './tools/order/get-transaction-stop-investigations/get-transaction-stop-investigations.query';
import { GetTransactionStopInvestigationsTool } from './tools/order/get-transaction-stop-investigations/get-transaction-stop-investigations.tool';
import { GetCustomerProspectsQuery } from './tools/party/get-customer-prospects/get-customer-prospects.query';
import { GetCustomerProspectsTool } from './tools/party/get-customer-prospects/get-customer-prospects.tool';
import { GetCustomerRelationshipsQuery } from './tools/party/get-customer-relationships/get-customer-relationships.query';
import { GetCustomerRelationshipsTool } from './tools/party/get-customer-relationships/get-customer-relationships.tool';
import { GetCustomerSecureMessagesQuery } from './tools/party/get-customer-secure-messages/get-customer-secure-messages.query';
import { GetCustomerSecureMessagesTool } from './tools/party/get-customer-secure-messages/get-customer-secure-messages.tool';
import { GetExternalUserPreferencesQuery } from './tools/party/get-external-user-preferences/get-external-user-preferences.query';
import { GetExternalUserPreferencesTool } from './tools/party/get-external-user-preferences/get-external-user-preferences.tool';
import { GetParticipantsQuery } from './tools/party/get-participants/get-participants.query';
import { GetParticipantsTool } from './tools/party/get-participants/get-participants.tool';
import { GetInterestConditionsQuery } from './tools/product/get-interest-conditions/get-interest-conditions.query';
import { GetInterestConditionsTool } from './tools/product/get-interest-conditions/get-interest-conditions.tool';
import { GetAccountOfficersQuery } from './tools/reference/get-account-officers/get-account-officers.query';
import { GetAccountOfficersTool } from './tools/reference/get-account-officers/get-account-officers.tool';
import { GetBalanceTypesQuery } from './tools/reference/get-balance-types/get-balance-types.query';
import { GetBalanceTypesTool } from './tools/reference/get-balance-types/get-balance-types.tool';
import { GetBrokersQuery } from './tools/reference/get-brokers/get-brokers.query';
import { GetBrokersTool } from './tools/reference/get-brokers/get-brokers.tool';
import { GetCategoriesQuery } from './tools/reference/get-categories/get-categories.query';
import { GetCategoriesTool } from './tools/reference/get-categories/get-categories.tool';
import { GetChequeTypesQuery } from './tools/reference/get-cheque-types/get-cheque-types.query';
import { GetChequeTypesTool } from './tools/reference/get-cheque-types/get-cheque-types.tool';
import { GetCompaniesQuery } from './tools/reference/get-companies/get-companies.query';
import { GetCompaniesTool } from './tools/reference/get-companies/get-companies.tool';
import { GetCountriesQuery } from './tools/reference/get-countries/get-countries.query';
import { GetCountriesTool } from './tools/reference/get-countries/get-countries.tool';
import { GetDealersQuery } from './tools/reference/get-dealers/get-dealers.query';
import { GetDealersTool } from './tools/reference/get-dealers/get-dealers.tool';
import { GetIndustriesQuery } from './tools/reference/get-industries/get-industries.query';
import { GetIndustriesTool } from './tools/reference/get-industries/get-industries.tool';
import { GetLanguageCodesQuery } from './tools/reference/get-language-codes/get-language-codes.query';
import { GetLanguageCodesTool } from './tools/reference/get-language-codes/get-language-codes.tool';
import { GetLookupsQuery } from './tools/reference/get-lookups/get-lookups.query';
import { GetLookupsTool } from './tools/reference/get-lookups/get-lookups.tool';
import { GetPurposesQuery } from './tools/reference/get-purposes/get-purposes.query';
import { GetPurposesTool } from './tools/reference/get-purposes/get-purposes.tool';
import { GetRateTextsQuery } from './tools/reference/get-rate-texts/get-rate-texts.query';
import { GetRateTextsTool } from './tools/reference/get-rate-texts/get-rate-texts.tool';
import { GetSectorsQuery } from './tools/reference/get-sectors/get-sectors.query';
import { GetSectorsTool } from './tools/reference/get-sectors/get-sectors.tool';
import { GetSystemDatesQuery } from './tools/reference/get-system-dates/get-system-dates.query';
import { GetSystemDatesTool } from './tools/reference/get-system-dates/get-system-dates.tool';
import { GetUsBeneficialOwnerTypesQuery } from './tools/reference/get-us-beneficial-owner-types/get-us-beneficial-owner-types.query';
import { GetUsBeneficialOwnerTypesTool } from './tools/reference/get-us-beneficial-owner-types/get-us-beneficial-owner-types.tool';
import { GetUsCustomerRatingsQuery } from './tools/reference/get-us-customer-ratings/get-us-customer-ratings.query';
import { GetUsCustomerRatingsTool } from './tools/reference/get-us-customer-ratings/get-us-customer-ratings.tool';
import { GetUsFdicClasscodesQuery } from './tools/reference/get-us-fdic-classcodes/get-us-fdic-classcodes.query';
import { GetUsFdicClasscodesTool } from './tools/reference/get-us-fdic-classcodes/get-us-fdic-classcodes.tool';
import { GetUsHoldTypesQuery } from './tools/reference/get-us-hold-types/get-us-hold-types.query';
import { GetUsHoldTypesTool } from './tools/reference/get-us-hold-types/get-us-hold-types.tool';
import { GetUsIndustriesQuery } from './tools/reference/get-us-industries/get-us-industries.query';
import { GetUsIndustriesTool } from './tools/reference/get-us-industries/get-us-industries.tool';
import { GetUsLoanCovenantsQuery } from './tools/reference/get-us-loan-covenants/get-us-loan-covenants.query';
import { GetUsLoanCovenantsTool } from './tools/reference/get-us-loan-covenants/get-us-loan-covenants.tool';
import { GetUsStatesQuery } from './tools/reference/get-us-states/get-us-states.query';
import { GetUsStatesTool } from './tools/reference/get-us-states/get-us-states.tool';
import { GetUtilityBeneficiariesQuery } from './tools/reference/get-utility-beneficiaries/get-utility-beneficiaries.query';
import { GetUtilityBeneficiariesTool } from './tools/reference/get-utility-beneficiaries/get-utility-beneficiaries.tool';

const QUERIES = [
  GetGuaranteesQuery,
  GetExpiringLimitsQuery,
  GetReviewLimitsQuery,
  GetLimitMasterGroupsQuery,
  GetSharedLimitsQuery,
  GetLetterOfCreditIncoTermsQuery,
  GetLetterOfCreditTenorsQuery,
  GetNostroAccountsQuery,
  GetVostroAccountsQuery,
  GetPaymentStopsQuery,
  GetDerivativeOptionAssignsQuery,
  GetDerivativeOptionExercisesQuery,
  GetDerivativeOptionExpiresQuery,
  GetRepoPositionMovementsQuery,
  GetRepoPositionsQuery,
  GetReverseRepoPositionMovementsQuery,
  GetReverseRepoPositionsQuery,
  GetPendingPaymentsQuery,
  GetPaymentFeesQuery,
  GetTransactionStopInvestigationsQuery,
  GetCustomerRelationshipsQuery,
  GetCustomerSecureMessagesQuery,
  GetCustomerProspectsQuery,
  GetParticipantsQuery,
  GetExternalUserPreferencesQuery,
  GetInterestConditionsQuery,
  GetAccountOfficersQuery,
  GetBalanceTypesQuery,
  GetChequeTypesQuery,
  GetCountriesQuery,
  GetIndustriesQuery,
  GetLanguageCodesQuery,
  GetBrokersQuery,
  GetCompaniesQuery,
  GetPurposesQuery,
  GetSectorsQuery,
  GetCategoriesQuery,
  GetDealersQuery,
  GetRateTextsQuery,
  GetSystemDatesQuery,
  GetLookupsQuery,
  GetUtilityBeneficiariesQuery,
  GetUsBeneficialOwnerTypesQuery,
  GetUsStatesQuery,
  GetUsCustomerRatingsQuery,
  GetUsHoldTypesQuery,
  GetUsFdicClasscodesQuery,
  GetUsLoanCovenantsQuery,
  GetUsIndustriesQuery,
];

const TOOLS = [
  GetGuaranteesTool,
  GetExpiringLimitsTool,
  GetReviewLimitsTool,
  GetLimitMasterGroupsTool,
  GetSharedLimitsTool,
  GetLetterOfCreditIncoTermsTool,
  GetLetterOfCreditTenorsTool,
  GetNostroAccountsTool,
  GetVostroAccountsTool,
  GetPaymentStopsTool,
  GetDerivativeOptionAssignsTool,
  GetDerivativeOptionExercisesTool,
  GetDerivativeOptionExpiresTool,
  GetRepoPositionMovementsTool,
  GetRepoPositionsTool,
  GetReverseRepoPositionMovementsTool,
  GetReverseRepoPositionsTool,
  GetPendingPaymentsTool,
  GetPaymentFeesTool,
  GetTransactionStopInvestigationsTool,
  GetCustomerRelationshipsTool,
  GetCustomerSecureMessagesTool,
  GetCustomerProspectsTool,
  GetParticipantsTool,
  GetExternalUserPreferencesTool,
  GetInterestConditionsTool,
  GetAccountOfficersTool,
  GetBalanceTypesTool,
  GetChequeTypesTool,
  GetCountriesTool,
  GetIndustriesTool,
  GetLanguageCodesTool,
  GetBrokersTool,
  GetCompaniesTool,
  GetPurposesTool,
  GetSectorsTool,
  GetCategoriesTool,
  GetDealersTool,
  GetRateTextsTool,
  GetSystemDatesTool,
  GetLookupsTool,
  GetUtilityBeneficiariesTool,
  GetUsBeneficialOwnerTypesTool,
  GetUsStatesTool,
  GetUsCustomerRatingsTool,
  GetUsHoldTypesTool,
  GetUsFdicClasscodesTool,
  GetUsLoanCovenantsTool,
  GetUsIndustriesTool,
];

@Module({
  imports: [MetricsModule],
  providers: [
    {
      provide: TemenosHttpClient,
      inject: [temenosConfig.KEY, Metrics],
      useFactory: (config: TemenosConfig, metrics: Metrics) =>
        new TemenosHttpClient(config, metrics),
    },
    ...QUERIES,
    ...TOOLS,
  ],
  exports: [TemenosHttpClient, ...QUERIES, ...TOOLS],
})
export class TemenosModule {}
