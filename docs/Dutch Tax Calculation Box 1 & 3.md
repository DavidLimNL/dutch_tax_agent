# **Technical Specification and Legislative Analysis: Dutch Personal Income Tax Calculation Engine (Box 1 & Box 3\) for Fiscal Partners (2022–2025)**

## **1\. Introduction: The Paradigm Shift in Dutch Fiscal Engineering**

The development of a tax calculation engine for the Dutch market covering the fiscal years 2022 through 2025 represents a unique challenge in the history of fiscal software engineering. Unlike typical updates that require mere parameter adjustments—changing a tax bracket threshold or updating an inflation index—this specific quadrennial period encompasses a fundamental rupture in the legal philosophy underlying the taxation of wealth in the Netherlands. For developers and fiscal analysts, this period is characterized not by a linear evolution of tax law, but by a concurrent operation of conflicting legal systems: the statutory systems legislated by Parliament and the remedial systems mandated by the Supreme Court (*Hoge Raad*).  
The primary complexity arises from the collapse of the "presumed return" (*forfaitair rendement*) system in Box 3 (income from savings and investments). Following the landmark "Christmas Ruling" (*Kerstarrest*) of December 24, 2021, and reinforced by the rulings of June 6 and June 14, 2024, the tax base for wealth can no longer be determined solely by static legislative formulas. Instead, a calculator must now function as a comparative engine, capable of simulating multiple tax liability scenarios—statutory fictitious returns versus actual realized and unrealized returns—to determine the definitive legal obligation.  
This report serves as a comprehensive technical specification for constructing such an engine. It is tailored specifically for a fiscal partnership profile where only one partner generates income from work (Box 1), while potentially both hold assets in Box 3\. This demographic profile introduces critical interaction effects between the two boxes, particularly regarding the transferability of tax credits (*heffingskortingen*) and the optimal allocation of the taxable base for assets. The analysis that follows provides the exhaustive legislative logic, mathematical algorithms, and data requirements necessary to model these liabilities with precision, ensuring that the resulting software architecture is robust enough to handle the "Schrödinger’s Tax" nature of the 2022–2025 period.

## ---

**2\. Structural Architecture of the Dutch Personal Income Tax System**

To build a compliant calculation engine, one must first map the structural interdependencies of the *Wet inkomstenbelasting 2001* (Income Tax Act 2001\) as it applied during these transition years. The system is compartmentalized into three "boxes," each treating a distinct source of income. While the boxes are theoretically closed systems—losses in one generally do not offset profits in another—they are mechanically linked through the calculation of *Aggregate Income* (*Verzamelinkomen*), which determines the eligibility and magnitude of tax credits.  
For the user profile in question—a couple with no children and no inheritance—the relevant compartments are Box 1 and Box 3\. Box 2 (substantial interest) is explicitly out of scope, simplifying the "Aggregate Income" calculation to the sum of Box 1 and Box 3 taxable incomes.

### **2.1 The Concept of Fiscal Partnership**

A defining feature of the Dutch system for couples is *Fiscal Partnership* (*Fiscaal Partnerschap*). This status acts as a powerful optimization variable within the tax algorithm. While income from labor (Box 1 wages) is strictly individual and cannot be shifted between partners, the *common income components* and *common deductions* can be allocated freely.  
For the target demographic, this allocation mechanism is the primary lever for tax minimization. The partner with no Box 1 income essentially has a "wasted" tax-free allowance and unused tax credits unless income is artificially attributed to them. By shifting the *yield basis* (*rendementsgrondslag*) of Box 3 assets to the non-working partner, the couple can utilize that partner's otherwise dormant General Tax Credit (*Algemene Heffingskorting*) to offset the wealth tax liability. The calculator must, therefore, not simply compute tax for Person A and Person B separately; it must run an optimization loop to determine the split of Box 3 assets that results in the global minimum tax liability for the household.

### **2.2 The Aggregate Income Feedback Loop**

A critical architectural detail often missed in simpler calculators is the feedback loop created by *Aggregate Income*. The magnitude of the General Tax Credit is inversely related to income; as income rises, the credit shrinks.

* **The Dependency:** The tax credit reduces the tax payable in Box 1\.  
* **The Conflict:** The credit amount depends on *Aggregate Income*, which includes Box 3 income.  
* **The Implication:** A higher return in Box 3 (whether actual or fictitious) increases Aggregate Income, which *decreases* the General Tax Credit, thereby effectively increasing the tax payable in Box 1\.  
* **Technical Requirement:** The calculator must determine the definitive Box 3 income *before* finalizing the Box 1 tax liability, or solve the system simultaneously.

## ---

**3\. Box 1: Taxation of Income from Work and Home**

For the working partner, the primary tax liability stems from Box 1\. This box aggregates income from employment, benefits, and the deemed income from an owner-occupied home (*eigenwoningforfait*), minus deductible expenses such as mortgage interest. For the non-working partner, this income is zero, yet their potential to absorb deductions remains a relevant factor.

### **3.1 The Progressive Bracket System (2022–2025)**

Since 2020, the Netherlands has moved towards a two-bracket system for taxpayers below the state pension (*AOW*) age. The first bracket includes both income tax and National Insurance contributions (*premie volksverzekeringen*), while the second bracket consists solely of income tax. However, the legislative changes for 2025 introduce a "sub-bracket" or intermediate rate, effectively creating a three-tier logic for calculation purposes.

#### **3.1.1 Evolution of Rates and Thresholds**

The following table details the precise parameters that must be hard-coded into the calculator's rate tables. Note specifically the divergence in 2025\.  
**Table 1: Box 1 Tax Brackets and Rates (Taxpayers \< AOW Age)**

| Fiscal Year | Bracket 1 Limit (€) | Rate 1 (Tax \+ NI) | Bracket 2 Limit (€) | Rate 2 (Tax Only) | Source |
| :---- | :---- | :---- | :---- | :---- | :---- |
| **2022** | Up to 69,398 | **37.07%** | \> 69,398 | **49.50%** | 1 |
| **2023** | Up to 73,031 | **36.93%** | \> 73,031 | **49.50%** | 1 |
| **2024** | Up to 75,518 | **36.97%** | \> 75,518 | **49.50%** | 1 |
| **2025** | Up to 38,441 | **35.82%** | \> 76,817 | **49.50%** | 1 |
| **2025 (Mid)** | 38,441 – 76,817 | **37.48%** |  |  | 3 |

**Technical Insight for 2025:** The introduction of the 35.82% rate for the first \~€38k in 2025 represents a tax cut for lower/middle incomes. The calculator logic must be updated to handle a standard progressive lookup: Tax \= (Min(Income, Limit1) \* Rate1) \+ (Max(0, Min(Income, Limit2) \- Limit1) \* Rate2) \+....

### **3.2 Tax Credits: The Calculation Engine's Core Reducer**

Tax credits (*heffingskortingen*) are not deductions from income; they are deductions from the calculated tax amount. This distinction is vital. If the calculated tax is €5,000 and the credit is €6,000, the tax payable is €0, but the remaining €1,000 credit usually evaporates (unless the fiscal partner transfer rule applies).

#### **3.2.1 The General Tax Credit (Algemene Heffingskorting \- AHK)**

The AHK is the most significant credit for the non-working partner. Since 2014, it has been income-dependent, phasing out as income increases. The calculator must implement a piecewise linear function to determine this credit.  
**Mathematical Definition of AHK (2022–2025):**

* **2022 Parameters:**  
  * Maximum Credit: **€2,888**  
  * Pivot Income: €21,317  
  * Phase-out Rate: 6.007%  
  * End Point: €69,398  
  * *Logic:* If Income \< €21,317, Credit \= €2,888. If Income \> €69,398, Credit \= €0. Between, use: 2888 \- 0.06007 \* (Income \- 21317).5  
* **2023 Parameters:**  
  * Maximum Credit: **€3,070**  
  * Pivot Income: €22,660  
  * Phase-out Rate: 6.095%  
  * End Point: €73,031  
  * *Logic:* 3070 \- 0.06095 \* (Income \- 22660).5  
* **2024 Parameters:**  
  * Maximum Credit: **€3,362**  
  * Pivot Income: €24,812  
  * Phase-out Rate: 6.63%  
  * End Point: €75,518  
  * *Logic:* 3362 \- 0.0663 \* (Income \- 24812).5  
* **2025 Parameters:**  
  * Maximum Credit: **€3,068**  
  * Pivot Income: €28,406  
  * Phase-out Rate: \~6.337%  
  * End Point: €76,817  
  * *Logic:* 3068 \- 0.06337 \* (Income \- 28406).5  
  * *Note on 2025:* The maximum credit *decreases* in 2025 compared to 2024, a notable break in trend designed to offset rate reductions in Box 1\.

#### **3.2.2 The "Aanrechtsubsidie" (Transferability of the AHK)**

For a couple with a single income, the transferability of the General Tax Credit from the non-working partner to the working partner is a crucial calculation. Historically, a non-working partner could cash out their AHK if their partner paid sufficient tax. However, this facility is being actively phased out based on the birth year of the non-working partner.  
**The 1963 Threshold Rule:**

* **Born Before Jan 1, 1963:** The non-working partner retains the right to transfer 100% of their AHK to the working partner, provided the working partner pays enough tax to cover it.6  
* **Born On/After Jan 1, 1963:** The transferability is subject to a strict phase-out that concluded in 2023\.  
  * **2022:** Max payout is limited to 6.67% of the total credit.  
  * **2023–2025:** **0% payout.** The credit evaporates if the non-working partner has no taxable income.6

Implication for the Calculator:  
The input field "Date of Birth" for the non-working partner is functionally a boolean switch for the years 2023–2025.

* *If DOB \>= 01-01-1963:* The calculator must warn the user that the AHK is wasted *unless* Box 3 income is allocated to this partner.  
* *Allocation Strategy:* By allocating Box 3 assets to the non-working partner, the calculator generates a tax liability for them. The AHK is then applied against this liability. This is mathematically superior to paying the Box 3 tax via the working partner (who has likely exhausted their credits). This "own-tax" usage is always allowed, regardless of birth year.

## ---

**4\. Box 3: The Crisis of Legitimacy and Calculation Methodologies**

The taxation of Box 3 (savings and investments) during 2022–2025 is the most technically demanding component of the system. It is characterized by the simultaneous existence of three different calculation methodologies, necessitated by the Supreme Court's ruling that the previous system violated the European Convention on Human Rights (EVRM).  
The calculator must support:

1. **The "Old" Method (Legacy):** Applicable only for 2022 comparison.  
2. **The "Savings Variant" (*Spaarvariant*):** The statutory standard for 2023–2025 (and 2022).  
3. **The "Actual Return" (*Werkelijk Rendement*):** The rebuttal method available for all years via objection.

### **4.1 The "Old" Method (2022 Only)**

Before the *Kerstarrest*, the Dutch system assumed that the more wealth one possessed, the higher the percentage invested in risky assets (stocks/real estate) rather than savings. This "fictitious asset mix" was rigid and independent of reality.  
Algorithm for 2022 Legacy Calculation:  
The system uses three capital brackets (schijven). For each bracket, a specific percentage is assumed to be savings (low return) and investments (high return).

* **Bracket 1 (€50,651 – €101,300):** Assumes 67% Savings (-0.01% return) and 33% Investments (5.53% return). Weighted return: \~1.82%.  
* **Bracket 2 (€101,301 – €1,013,000):** Assumes 21% Savings and 79% Investments. Weighted return: \~4.37%.  
* **Bracket 3 (\> €1,013,000):** Assumes 0% Savings and 100% Investments. Return: 5.53%.

*User Impact:* This method was advantageous for aggressive investors (who held 100% stocks but were taxed as if they held 67% cash in Bracket 1). It was punitive for savers. For 2022, the calculator must compute this result and compare it against the "Savings Variant," automatically selecting the lower tax for the user.9

### **4.2 The "Savings Variant" (Statutory Standard 2023–2025)**

The "Legal Restoration Act" (*Wet rechtsherstel box 3*) and subsequent "Bridging Act" (*Overbruggingswet*) introduced the **Savings Variant**. This method abandons the fictitious mix. It looks at the *actual* capital allocated to three distinct categories but applies *fictitious* rates of return to those categories.  
**The Three Asset Categories:**

1. **Category I: Bank Assets (*Banktegoeden*):** Savings accounts, cash, deposits.  
2. **Category II: Other Assets (*Overige bezittingen*):** Stocks, bonds, crypto, mutual funds, real estate, loans receivable.  
3. **Category III: Debts (*Schulden*):** Mortgage on 2nd home, student loans, consumer credit.

#### **4.2.1 Fictitious Return Rates (The Forfait)**

These rates are critical constants. The rate for "Other Assets" is fixed in advance based on long-term averages. The rates for "Savings" and "Debts" are retrospective, based on actual market averages for that year, meaning definitive rates for 2024/2025 are often finalized after the tax year ends.  
**Table 3: Fictitious Return Rates (2022–2025)**

| Category | 2022 | 2023 | 2024 | 2025 (Prov.) | Source |
| :---- | :---- | :---- | :---- | :---- | :---- |
| **I: Savings** | 0.00% | 0.92% | 1.44% | 1.44% | 11 |
| **II: Other Assets** | 5.53% | 6.17% | 6.04% | 5.88% | 13 |
| **III: Debts** | 2.28% | 2.46% | 2.61% | 2.62% | 13 |

**Data Note:** The 2025 rates are provisional (*voorlopig*). The calculator should explicitly label these as "estimates based on current government projections" to manage user expectations.

#### **4.2.2 Exemptions and Thresholds**

* **Tax-Free Allowance (*Heffingsvrij Vermogen*):** Deducted from the net assets before tax calculation.  
  * 2022: €50,650 (Partners: €101,300)  
  * 2023: €57,000 (Partners: €114,000)  
  * 2024: €57,000 (Partners: €114,000)  
  * 2025: €57,684 (Partners: €115,368) 15  
* **Debt Threshold (*Schuldendrempel*):** Debts are only deductible insofar as they exceed this threshold.  
  * 2022: €3,200 (Partners: €6,400)  
  * 2023: €3,400 (Partners: €6,800)  
  * 2024: €3,700 (Partners: €7,400)  
  * 2025: €3,800 (Partners: €7,600) 11  
* **Green Investments (*Groene Beleggingen*):** A separate exemption applies here.  
  * 2024: Exemption up to €71,251 per person.  
  * 2025: **Drastic Reduction** to €26,312 per person.17 This is a major "cliff" the calculator must highlight for users carrying green funds.

### **4.3 The "Actual Return" Method (Rebuttal Scheme)**

Following the Supreme Court rulings of June 6 and June 14, 2024, taxpayers have the right to be taxed on their **Actual Return** (*Werkelijk Rendement*) if it is demonstrably lower than the fictitious return calculated by the Savings Variant. This creates a "no-lose" scenario for the taxpayer, but a high complexity burden for the calculator.

#### **4.3.1 Definition of Actual Return**

The definition provided by the Hoge Raad is comprehensive and deviates significantly from intuitive accounting.

* **Scope:** It includes the entire Box 3 capital (no tax-free allowance is used in the *calculation* of the return percentage, though it influences the final comparison).  
* **Direct Returns:** Interest, dividends, and rental income received.  
* **Indirect Returns:** **Unrealized capital gains and losses.** If a stock portfolio rises in value from €100k to €120k, the €20k is taxable income, even if not sold. Conversely, a drop in value is a deductible loss.18  
* **Cost Deduction:** **Prohibited.** Costs such as bank fees, brokerage commissions, or property management fees are *not* deductible.  
* **Interest Deduction:** Interest paid on Box 3 debts *is* deductible.  
* **Real Estate Specifics:**  
  * Return \= (WOZ Value End \- WOZ Value Start) \+ Net Rental Income.  
  * For own-use second homes, the imputed rental value is deemed **zero**.20  
* **Nominalism:** No correction for inflation is permitted.19

#### **4.3.2 The "Paper Gain" Trap**

Because unrealized gains are included, a user with a portfolio that appreciated significantly (e.g., in 2023 or 2024\) might find the Fictitious System (capped at \~6%) more favorable than the Actual Return system (which might show 15%+ actual gains). The Rebuttal Scheme is primarily a rescue mechanism for years with market downturns (like 2022\) or for asset classes with structurally low yields (like bonds).

## ---

**5\. Algorithmic Logic for the Calculator**

To implement this legislative web, the calculator must execute a multi-step logic flow.

### **5.1 Step 1: Net Asset Calculation (Per Partner & Joint)**

Calculate the net value of assets on January 1st (Peildatum).

* Net\_Savings \= Total\_Savings  
* Net\_Other \= Total\_Investments \+ Total\_Property \+ Total\_Crypto  
* Deductible\_Debt \= Max(0, Total\_Debt \- Debt\_Threshold)  
* Rentability\_Base \= Net\_Savings \+ Net\_Other \- Deductible\_Debt

### **5.2 Step 2: Fictitious Return Calculation (Savings Variant)**

Compute the weighted return based on the asset mix.

* Return\_Savings \= Net\_Savings \* Rate\_Savings\_Year  
* Return\_Other \= Net\_Other \* Rate\_Other\_Year  
* Return\_Debt \= Deductible\_Debt \* Rate\_Debt\_Year  
* Total\_Fictitious\_Return \= Return\_Savings \+ Return\_Other \- Return\_Debt  
  * *Constraint:* Cannot be \< 0\.  
* Effective\_Rate \= Total\_Fictitious\_Return / Rentability\_Base

### **5.3 Step 3: Taxable Base & Tax Liability**

Apply the tax-free allowance.

* Taxable\_Base \= Max(0, Rentability\_Base \- (Tax\_Free\_Allowance \* Partners))  
* Box\_3\_Income\_Statutory \= Taxable\_Base \* Effective\_Rate  
* Box\_3\_Tax\_Statutory \= Box\_3\_Income\_Statutory \* Tax\_Rate\_Box3\_Year  
  * *Box 3 Tax Rates:* 31% (2022), 32% (2023), 36% (2024), 36% (2025).21

### **5.4 Step 4: Actual Return Calculation (Rebuttal Check)**

This step requires additional user inputs regarding flow (dividends, interest) and delta (value changes).

* Actual\_Return\_Total \= Interest\_Received \+ Dividends\_Received \+ Rental\_Income \+ (Value\_End \- Value\_Start \- Deposits \+ Withdrawals) \- Interest\_Paid  
* **Comparative Logic:** The Hoge Raad ruled that the *tax burden* under the new system should not exceed the tax burden on the actual return.  
  * Theoretical\_Tax\_Actual \= Actual\_Return\_Total \* Tax\_Rate\_Box3\_Year  
  * *Optimization:* Final\_Tax\_Liability \= Min(Box\_3\_Tax\_Statutory, Theoretical\_Tax\_Actual)  
  * *Note:* If Actual\_Return\_Total is negative, the tax is €0. Currently, no loss carry-forward is legislated for this specific rebuttal scheme.22

## ---

**6\. Fiscal Partnership Optimization Algorithm**

This is the "killer feature" for the requested user profile. The calculator must determine the optimal allocation ratio ($r$) of the Box 3 Taxable Base between Partner A (Working) and Partner B (Non-Working).  
**Variables:**

* $T\_{A}$: Tax liability of Partner A (Box 1 \+ allocated Box 3).  
* $T\_{B}$: Tax liability of Partner B (Allocated Box 3 only).  
* $C\_{A}$: General Tax Credit for A (Dependent on aggregate income).  
* $C\_{B}$: General Tax Credit for B (Dependent on aggregate income).  
* $Base\_{3}$: Total Box 3 Taxable Base.

**The Logic:**

1. **Default:** Determine $C\_{B}$ based on Partner B's €0 income. (e.g., \~€3,000).  
2. **Target:** Allocate enough $Base\_{3}$ to Partner B such that their calculated Box 3 tax equals $C\_{B}$.  
   * $Target\\\_Tax\_{B} \= C\_{B}$  
   * $Required\\\_Income\_{B} \= Target\\\_Tax\_{B} / Rate\_{Box3}$  
   * $Required\\\_Allocation\_{B} \= Required\\\_Income\_{B} / Effective\\\_Rate$  
3. **Constraint Check:** Is $Required\\\_Allocation\_{B} \\le Base\_{3}$?  
   * **Yes:** Allocate $Required\\\_Allocation\_{B}$ to Partner B. The remainder goes to Partner A. Partner B pays €0 net tax (Tax \- Credit \= 0). Partner A pays tax on the remainder.  
   * **No:** Allocate 100% to Partner B. They pay €0 net tax, and a portion of their credit remains unused (wasted).

**Why this works:** Partner A likely has a high Box 1 income, reducing their specific $C\_{A}$ (perhaps to zero). Any Box 3 tax allocated to A is paid in full. Box 3 tax allocated to B is absorbed by $C\_{B}$ (which otherwise dissolves if B was born after 1962). This arbitrage can save the couple up to \~€3,000 annually.

## ---

**7\. Required Data Inputs (Database Specification)**

To execute the logic above, the calculator requires a structured set of inputs. The following list is exhaustive.

### **7.1 Entity: Fiscal Year & Partnership**

* Fiscal\_Year: Enum  
* Is\_Fiscal\_Partner: Boolean (True per user prompt)

### **7.2 Entity: Partner A (Working)**

* Date\_of\_Birth: Date (Determines AOW status and credit rates).  
* Box\_1\_Gross\_Income: Decimal (€).  
* Withheld\_Wage\_Tax: Decimal (€) (Optional, for net refund calculation).

### **7.3 Entity: Partner B (Non-Working)**

* Date\_of\_Birth: Date (**Critical** for "Aanrechtsubsidie" phase-out logic).  
* Box\_1\_Gross\_Income: Fixed at €0.

### **7.4 Entity: Box 3 Assets (Snapshot Jan 1st)**

* Bank\_Savings: Decimal (€).  
* Investments\_Other: Decimal (€).  
* Green\_Investments: Decimal (€) (Apply 2025 cap logic).  
* Debts: Decimal (€).

### **7.5 Entity: Actual Return Data (Optional/Advanced Mode)**

* Interest\_Received\_Total: Decimal (€).  
* Dividends\_Received\_Total: Decimal (€).  
* Rental\_Income\_Total: Decimal (€).  
* Portfolio\_Value\_Dec\_31: Decimal (€).  
* Portfolio\_Deposits: Decimal (€) (Money added during year).  
* Portfolio\_Withdrawals: Decimal (€) (Money removed during year).  
* Debt\_Interest\_Paid: Decimal (€).

## ---

**8\. Narrative Scenarios & Strategic Nuances**

### **8.1 The "Peildatumarbitrage" (Reference Date Arbitration) Risk**

The calculator must be aware of anti-abuse rules regarding "Peildatumarbitrage." This occurs when taxpayers temporarily shift assets (e.g., selling stocks to cash on Dec 30 and buying back Jan 2\) to exploit the lower rate on savings.

* **Rule:** If transactions occur within a 3-month window around Jan 1st with the primary aim of tax reduction, the *highest* rate applies to the shifted capital.  
* **Implementation:** A warning note in the calculator advising users that short-term shifts are ignored by the Belastingdienst.23

### **8.2 The 2022 "Golden Year" for Objections**

The year 2022 presents a unique anomaly. While the "Old Method" assumed a portfolio mix of \~33% investments for small savers, and the "Savings Variant" corrected this, the "Actual Return" method is often the absolute winner for investors.

* **Context:** 2022 was a bear market (stocks and bonds fell).  
* **Result:** Most investors had a *negative* actual return.  
* **Strategy:** The calculator should aggressively prompt 2022 users to input actual return data. If the portfolio value dropped, the Box 3 tax liability is likely **zero**, triggering a massive refund compared to the statutory system which assumes a \~5.53% gain regardless of market reality.

### **8.3 The Green Investment "Cliff" of 2025**

For users utilizing "Groenfonds" tax breaks, 2025 is a shock. The exemption drops from \~€71k to \~€26k.

* **Scenario:** A couple holding €140k in green funds paid €0 tax on them in 2024 (2x €71k exemption).  
* **2025 Outcome:** Exemption is capped at \~€52k (2x €26k). The remaining €88k suddenly enters the taxable base at the "Other Assets" rate (5.88%).  
* **Calculator Alert:** The system must highlight this specific variance when switching years from 2024 to 2025\.17

### **8.4 The "Paper Gains" Dilemma**

Users often misunderstand "Actual Return" as "Realized Return." The calculator must clarify via tooltips that *unrealized* gains are taxable.

* **Example:** You bought Bitcoin at €20k in Jan 2023\. It is €40k in Dec 2023\. You did not sell.  
* **Tax:** You owe tax on the €20k gain.  
* **Liquidity Risk:** Users may owe tax on gains they haven't cashed out. The calculator provides transparency on this liability.

## ---

**9\. Conclusion: Building for Uncertainty**

The construction of a tax calculator for the 2022–2025 period is an exercise in managing legislative volatility. By implementing the dual-engine logic (Statutory vs. Actual) and integrating the partner optimization algorithm, the tool will not only calculate compliance but actively uncover tax-saving opportunities inherent in the transition rules.  
The core value proposition for the user lies in the **Partner Allocation Algorithm**—leveraging the non-working partner's tax credit against Box 3 liability—and the **Rebuttal Module**, which identifies years (like 2022\) where the statutory assumption diverges from economic reality. This architecture ensures the calculator is not merely a passive form-filler, but a strategic fiscal advisor.

#### **Works cited**

1. Box 1 tarief AOW \- Tarieven & Cijfers \- Jongbloed Fiscaal Juristen, accessed on December 20, 2025, [https://www.jongbloed-fiscaaljuristen.nl/databank/tarieven\_&\_cijfers/tarieven\_inkomstenbelasting/](https://www.jongbloed-fiscaaljuristen.nl/databank/tarieven_&_cijfers/tarieven_inkomstenbelasting/)  
2. Box 1: uitleg en tarieven \- Belastingdienst, accessed on December 20, 2025, [https://www.belastingdienst.nl/wps/wcm/connect/bldcontentnl/belastingdienst/prive/inkomstenbelasting/heffingskortingen\_boxen\_tarieven/boxen\_en\_tarieven/box\_1/box\_1](https://www.belastingdienst.nl/wps/wcm/connect/bldcontentnl/belastingdienst/prive/inkomstenbelasting/heffingskortingen_boxen_tarieven/boxen_en_tarieven/box_1/box_1)  
3. Hoeveel inkomstenbelasting moet ik betalen? \- Belastingdienst, accessed on December 20, 2025, [https://www.belastingdienst.nl/wps/wcm/connect/nl/werk-en-inkomen/content/hoeveel-inkomstenbelasting-betalen](https://www.belastingdienst.nl/wps/wcm/connect/nl/werk-en-inkomen/content/hoeveel-inkomstenbelasting-betalen)  
4. Soorten inkomstenbelasting \- Rijksoverheid, accessed on December 20, 2025, [https://www.rijksoverheid.nl/onderwerpen/inkomstenbelasting/soorten-inkomstenbelasting](https://www.rijksoverheid.nl/onderwerpen/inkomstenbelasting/soorten-inkomstenbelasting)  
5. Algemene heffingskorting \- CAK, accessed on December 20, 2025, [https://www.hetcak.nl/zorgverzekering-buitenland/pensioen-uitkering/financiele-informatie/jaarafrekening/heffingskortingen/algemene-heffingskorting/](https://www.hetcak.nl/zorgverzekering-buitenland/pensioen-uitkering/financiele-informatie/jaarafrekening/heffingskortingen/algemene-heffingskorting/)  
6. Weinig of geen inkomen – toch heffingskortingen laten uitbetalen? \- Belastingdienst, accessed on December 20, 2025, [https://www.belastingdienst.nl/wps/wcm/connect/nl/aftrek-en-kortingen/content/heffingskortingen-laten-uitbetalen](https://www.belastingdienst.nl/wps/wcm/connect/nl/aftrek-en-kortingen/content/heffingskortingen-laten-uitbetalen)  
7. Heffingskorting 2025 niet werkende partner \- bijnametpensioen.nl, accessed on December 20, 2025, [https://bijnametpensioen.nl/heffingskorting-niet-werkende-partner-2024/](https://bijnametpensioen.nl/heffingskorting-niet-werkende-partner-2024/)  
8. Kan ik de algemene heffingskorting laten uitbetalen? \- ANBO-PCOB, accessed on December 20, 2025, [https://anbo-pcob.nl/advies-en-hulp/vragen-en-antwoorden/belasting/kan-ik-de-algemene-heffingskorting-laten-uitbetalen/](https://anbo-pcob.nl/advies-en-hulp/vragen-en-antwoorden/belasting/kan-ik-de-algemene-heffingskorting-laten-uitbetalen/)  
9. Hoe wordt mijn box 3-inkomen over 2022 berekend? \- Belastingdienst, accessed on December 20, 2025, [https://www.belastingdienst.nl/wps/wcm/connect/nl/box-3/content/berekening-box-3-inkomen-2022](https://www.belastingdienst.nl/wps/wcm/connect/nl/box-3/content/berekening-box-3-inkomen-2022)  
10. Vermogensbelasting 2022 en eerder \- Consumentenbond, accessed on December 20, 2025, [https://www.consumentenbond.nl/belastingaangifte/zelf-aangifte-doen/vermogensbelasting-2022-en-eerder](https://www.consumentenbond.nl/belastingaangifte/zelf-aangifte-doen/vermogensbelasting-2022-en-eerder)  
11. Box 3 en particulieren \- Tax \- Onze dienstverlening \- PwC, accessed on December 20, 2025, [https://www.pwc.nl/nl/dienstverlening/tax/wegwijzer-box-3/box-3-en-particulieren.html](https://www.pwc.nl/nl/dienstverlening/tax/wegwijzer-box-3/box-3-en-particulieren.html)  
12. Hoe wordt mijn box 3-inkomen over 2024 berekend? \- Belastingdienst, accessed on December 20, 2025, [https://www.belastingdienst.nl/wps/wcm/connect/nl/box-3/content/berekening-box-3-inkomen-2024](https://www.belastingdienst.nl/wps/wcm/connect/nl/box-3/content/berekening-box-3-inkomen-2024)  
13. Box 3: dit zijn de rendementspercentages voor 2023, 2024 en 2025 \- Van Lanschot Kempen, accessed on December 20, 2025, [https://www.vanlanschotkempen.com/nl-nl/private-banking/inspiratie/beleggen-en-sparen/de-rendementspercentages-in-box-3-voor-2023-2024-en-2025](https://www.vanlanschotkempen.com/nl-nl/private-banking/inspiratie/beleggen-en-sparen/de-rendementspercentages-in-box-3-voor-2023-2024-en-2025)  
14. Wat zijn de rendementen voor box 3? \- Rabobank, accessed on December 20, 2025, [https://www.rabobank.nl/private-banking/vermogensvragen/rendementen-box-3](https://www.rabobank.nl/private-banking/vermogensvragen/rendementen-box-3)  
15. Heffingsvrij vermogen | Belastingdienst, accessed on December 20, 2025, [https://www.belastingdienst.nl/wps/wcm/connect/nl/box-3/content/heffingsvrij-vermogen](https://www.belastingdienst.nl/wps/wcm/connect/nl/box-3/content/heffingsvrij-vermogen)  
16. Hoe is het box 3-inkomen op mijn voorlopige aanslag 2025 berekend? \- Belastingdienst, accessed on December 20, 2025, [https://www.belastingdienst.nl/wps/wcm/connect/nl/box-3/content/box-3-inkomen-op-voorlopige-aanslag-2025](https://www.belastingdienst.nl/wps/wcm/connect/nl/box-3/content/box-3-inkomen-op-voorlopige-aanslag-2025)  
17. Plannen kabinet inkomstenbelasting | Prinsjesdag: Belastingplan 2026 | Rijksoverheid.nl, accessed on December 20, 2025, [https://www.rijksoverheid.nl/onderwerpen/belastingplan/inkomstenbelasting](https://www.rijksoverheid.nl/onderwerpen/belastingplan/inkomstenbelasting)  
18. Meer info over rechtsherstel box 3 na uitspraken Hoge Raad juni 2024 bekend gemaakt \- Private Banking \- Rabobank, accessed on December 20, 2025, [https://www.rabobank.nl/particulieren/private-banking/vermogensvragen/Meer-info-over-rechtsherstel-box-3-na-uitspraken-Hoge-Raad-juni-2024-bekend-gemaakt](https://www.rabobank.nl/particulieren/private-banking/vermogensvragen/Meer-info-over-rechtsherstel-box-3-na-uitspraken-Hoge-Raad-juni-2024-bekend-gemaakt)  
19. Hoge Raad: Box 3 moet uitgaan van werkelijk rendement \- Van Lanschot Kempen, accessed on December 20, 2025, [https://www.vanlanschotkempen.com/nl-nl/private-banking/inspiratie/vermogensregie/hoge-raad-box-3-moet-uitgaan-van-werkelijk-rendement](https://www.vanlanschotkempen.com/nl-nl/private-banking/inspiratie/vermogensregie/hoge-raad-box-3-moet-uitgaan-van-werkelijk-rendement)  
20. Hoge Raad: voor bepaling werkelijke rendement in box 3 is voordeel wegens eigen gebruik onroerende zaken nihil, ook geeft Hoge Raad regels over wijze van berekening van ongerealiseerde waardeveranderingen, accessed on December 20, 2025, [https://www.hogeraad.nl/actueel/nieuwsoverzicht/2024/december/hoge-raad-bepaling-werkelijke-rendement-box-3-voordeel-wegens-eigen/](https://www.hogeraad.nl/actueel/nieuwsoverzicht/2024/december/hoge-raad-bepaling-werkelijke-rendement-box-3-voordeel-wegens-eigen/)  
21. Box 3 belasting: tarieven en vrijstellingen in 2025 en 2026 \- MKB Servicedesk, accessed on December 20, 2025, [https://www.mkbservicedesk.nl/belastingen/inkomstenbelasting/box-3-tarieven-en-vrijstellingen](https://www.mkbservicedesk.nl/belastingen/inkomstenbelasting/box-3-tarieven-en-vrijstellingen)  
22. Box 3: tegenbewijsregeling, analyse arrest en vervolgproces \- PwC, accessed on December 20, 2025, [https://www.pwc.nl/nl/actueel-en-publicaties/belastingnieuws/inkomen/Box-3-tegenbewijsregeling-analyse-arrest-en-vervolgproces.html](https://www.pwc.nl/nl/actueel-en-publicaties/belastingnieuws/inkomen/Box-3-tegenbewijsregeling-analyse-arrest-en-vervolgproces.html)  
23. Box 3: vermogen verplaatsen rond 1 januari, wat mag wel en niet? | Evi van Lanschot, accessed on December 20, 2025, [https://www.evivanlanschot.nl/kennis/vermogensregie/box-3-vermogen-verplaatsen-rond-1-januari-wat-mag-wel-en-niet](https://www.evivanlanschot.nl/kennis/vermogensregie/box-3-vermogen-verplaatsen-rond-1-januari-wat-mag-wel-en-niet)