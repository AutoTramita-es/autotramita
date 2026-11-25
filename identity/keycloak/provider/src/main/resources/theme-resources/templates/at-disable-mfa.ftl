<#import "template.ftl" as layout>
<#import "buttons.ftl" as buttons>

<@layout.registrationLayout displayMessage=false; section>
<!-- template: at-disable-mfa.ftl -->
    <#if section = "header">
        ${msg("atDisableMfaTitle")}
    <#elseif section = "form">
        <div id="at-disable-mfa-text" class="${properties.kcContentWrapperClass!}">
            ${msg("atDisableMfaMessage")}
        </div>
        <form id="at-disable-mfa-form" class="${properties.kcFormClass!}" action="${url.loginAction}" method="POST">
            <input type="hidden" name="confirm" value="DISABLE_MFA"/>
            <@buttons.actionGroup>
                <@buttons.button name="accept" id="at-disable-mfa-accept" label="atDisableMfaConfirm" class=["kcButtonPrimaryClass"]/>
                <@buttons.button name="cancel-aia" id="at-disable-mfa-decline" label="doDecline" class=["kcButtonSecondaryClass"]/>
            </@buttons.actionGroup>
        </form>
    </#if>
</@layout.registrationLayout>
