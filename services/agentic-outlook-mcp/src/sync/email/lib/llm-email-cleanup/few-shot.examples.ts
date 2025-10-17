export const FEW_SHOT_EXAMPLES = [
  {
    name: 'Bank-style red caution table',
    html: `<table class="MsoNormalTable" border="0" cellpadding="0"><tbody><tr><td style="padding:.75pt .75pt .75pt .75pt"><div style="border:solid #FF2D00 1.5pt; padding:2.0pt 2.0pt 2.0pt 2.0pt"><p class="MsoNormal" style="background:#FF2D00"><strong><span style="font-family:&quot;Cambria&quot;,serif; color:white">CAUTION:</span></strong><span style="color:black"> </span><span style="font-family:&quot;Cambria&quot;,serif; color:white">This message is from an EXTERNAL sender – be vigilant, particularly with links and attachments. If you suspect it, report it immediately using the phishing button or by forwarding it to <a href="mailto:phishing@example.com">phishing@example.com</a> (<a href="mailto:cfc@example.us">cfc@example.us</a> for US users).</span></p></div></td></tr></tbody></table>`,
    expect: JSON.stringify({
      type: 'banner',
      reason: 'Top-of-email external warning with strong styling and vendor/security language.',
      confidence: 0.95,
    }),
  },
  {
    name: 'Dark strip EXTERNAL EMAIL warning',
    html: `<div>
<p style="background-color:#073B4C;padding:0.2em;border:0 solid #073B4C;"><span style="color:white;font-family:HelveticaNeue-Light;"><strong>EXTERNAL EMAIL</strong></span> <span style="color:white;font-family:HelveticaNeue-Light;">DO NOT CLICK links or attachments unless you recognize the sender and know the content is safe.</span></p>
<div>`,
    expect: JSON.stringify({
      type: 'banner',
      reason: 'External email warning in a top strip; short cautionary text.',
      confidence: 0.95,
    }),
  },
  {
    name: "Outlook 'You don't often get email...' with aka.ms link",
    html: `<table align="left" border="0" cellspacing="0" cellpadding="0" style="width:100%;border-spacing:0;border-width:0;bottom:revert!important;letter-spacing:revert!important;line-height:revert!important;opacity:revert!important;order:revert!important;outline:revert!important;overflow:revert!important;tab-size:revert!important;text-orientation:revert!important;text-overflow:revert!important;top:revert!important;word-break:revert!important;word-spacing:revert!important;writing-mode:revert!important;zoom:revert!important;float:none!important;">
<tr style="bottom:revert!important;letter-spacing:revert!important;line-height:revert!important;opacity:revert!important;order:revert!important;outline:revert!important;overflow:revert!important;tab-size:revert!important;text-orientation:revert!important;text-overflow:revert!important;top:revert!important;word-break:revert!important;word-spacing:revert!important;writing-mode:revert!important;zoom:revert!important;">
<td valign="middle" bgcolor="#A6A6A6" cellpadding="7px 2px 7px 2px" style="width:0;padding:7px 2px;bottom:revert!important;letter-spacing:revert!important;line-height:revert!important;opacity:revert!important;order:revert!important;outline:revert!important;overflow:revert!important;tab-size:revert!important;text-orientation:revert!important;text-overflow:revert!important;top:revert!important;word-break:revert!important;word-spacing:revert!important;writing-mode:revert!important;zoom:revert!important;"></td>
<td valign="middle" bgcolor="#EAEAEA" cellpadding="7px 5px 7px 15px" color="#212121" style="font-size:12px;font-family:wf_segoe-ui_normal,Segoe UI,Segoe WP,Tahoma,Arial,sans-serif!important;width:100%;padding:7px 5px 7px 15px;writing-mode:revert!important;word-spacing:revert!important;word-break:revert!important;top:revert!important;text-overflow:revert!important;text-orientation:revert!important;tab-size:revert!important;overflow:revert!important;outline:revert!important;order:revert!important;opacity:revert!important;line-height:revert!important;letter-spacing:revert!important;bottom:revert!important;zoom:revert!important;word-wrap:break-word!important;">
<div style="bottom:revert!important;letter-spacing:revert!important;line-height:revert!important;opacity:revert!important;order:revert!important;outline:revert!important;overflow:revert!important;tab-size:revert!important;text-orientation:revert!important;text-overflow:revert!important;top:revert!important;word-break:revert!important;word-spacing:revert!important;writing-mode:revert!important;zoom:revert!important;">You don't often get email from nparsons@pbs-santander.com. <a href="https://aka.ms/LearnAboutSenderIdentification" data-auth="NotApplicable" style="opacity:revert!important;">Learn why this is important</a> </div></td>
<td align="left" valign="middle" bgcolor="#EAEAEA" cellpadding="7px 5px 7px 5px" color="#212121" style="font-size:12px;font-family:wf_segoe-ui_normal,Segoe UI,Segoe WP,Tahoma,Arial,sans-serif!important;width:75px;padding:7px 5px;writing-mode:revert!important;word-spacing:revert!important;word-break:revert!important;top:revert!important;text-overflow:revert!important;text-orientation:revert!important;tab-size:revert!important;overflow:revert!important;outline:revert!important;order:revert!important;opacity:revert!important;line-height:revert!important;letter-spacing:revert!important;bottom:revert!important;zoom:revert!important;word-wrap:break-word!important;"></td></tr></table>`,
    expect: JSON.stringify({
      type: 'banner',
      reason: 'Outlook external-sender notice with aka.ms safety link; appears at top.',
      confidence: 0.95,
    }),
  },
];
