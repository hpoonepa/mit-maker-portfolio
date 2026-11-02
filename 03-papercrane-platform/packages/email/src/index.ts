/**
 * @papercrane/email — public API.
 *
 * The sender is template-agnostic; callers pick a template by name and pass
 * the matching data object. Type narrowing on `TemplateDataMap` ensures the
 * data shape is checked at the call site.
 */
export { sendEmail } from './sender';
export type {
  SendEmailInput,
  SendEmailResult,
  SenderOptions,
  SenderLogger,
  TemplateName,
  TemplateDataMap,
} from './sender';

export type { InviteData } from './templates/Invite';
export type { PasswordResetData } from './templates/PasswordReset';
export type { JobCompleteData } from './templates/JobComplete';
export type { JobFailedData } from './templates/JobFailed';
export type { BillingReceiptData, BillingLineItem } from './templates/BillingReceipt';
export type { WelcomeData } from './templates/WelcomeNewUser';
