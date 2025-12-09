def determine_workflow_outcome(inputs):
    # Extract inputs with defaults
    under_specialist_clinic = inputs.get('under_specialist_clinic', False)
    total_cholesterol = inputs.get('total_cholesterol', 0)
    prevention_type = inputs.get('prevention_type', 'Primary')
    taking_lipid_lowering_therapy = inputs.get('taking_lipid_lowering_therapy', False)
    optimised_on_treatment = inputs.get('optimised_on_treatment', False)
    qrisk2_3_score = inputs.get('qrisk2_3_score', 0)
    taking_maximally_tolerated_statin = inputs.get('taking_maximally_tolerated_statin', False)
    ldl_cholesterol = inputs.get('ldl_cholesterol', 0)
    months_on_inclisiran = inputs.get('months_on_inclisiran', 0)
    
    # First decision: Under Specialist Clinic?
    if under_specialist_clinic:
        # Check if optimised on treatment
        if optimised_on_treatment:
            return "No Further Action needed - specialist managing care"
        else:
            # Not optimised - need to send for treatment adjustment
            return "Send Lipid Lowering Therapy AccuRx with self booking link"
    
    # Not under specialist clinic - Assess Total Cholesterol Result
    # Normal is 5 or below, >7.5 is high, raised is >5 and <=7.5
    
    if total_cholesterol > 7.5:
        # High cholesterol - check if optimised on treatment
        if optimised_on_treatment:
            # Consider Lipid Clinic Referral -> Refer to specialist
            return "Refer to specialist"
        else:
            # Send Lipid Lowering Therapy AccuRx with self booking link -> Consultation
            return "Consultation"
    
    elif total_cholesterol > 5:
        # Raised cholesterol - Normal or Raised? -> Raised
        # Taking Lipid Lowering Therapy?
        if taking_lipid_lowering_therapy:
            # Are They Optimised on treatment?
            if optimised_on_treatment:
                # Mark as No Further Action
                return "Mark as No Further Action"
            else:
                # Send Lipid Lowering Therapy AccuRx with self booking link
                return "Send Lipid Lowering Therapy AccuRx with self booking link"
        else:
            # Not taking lipid lowering therapy
            # Calculate QRISK2/3
            if qrisk2_3_score >= 10:
                # High risk - Send Lipid Lowering Therapy AccuRx with self booking link
                return "Send Lipid Lowering Therapy AccuRx with self booking link"
            else:
                # Low risk - Send High Cholesterol - Low QRISK AccuRx with self booking link
                return "Send High Cholesterol - Low QRISK AccuRx with self booking link"
    
    else:
        # Normal cholesterol (<=5) - Normal or Raised? -> Normal
        # Mark as Satisfactory path, but we need to check prevention type for Secondary prevention
        
        if prevention_type == "Secondary":
            # Secondary prevention path - need to check if on maximally tolerated statin
            if taking_maximally_tolerated_statin:
                # Assess LDL
                if ldl_cholesterol <= 2:
                    return "No Further Action"
                elif ldl_cholesterol > 2 and ldl_cholesterol <= 2.5:
                    # LDL 2-2.5 - Add in Ezetimibe
                    return "Add in Ezetimibe"
                elif ldl_cholesterol >= 2.6:
                    # LDL >= 2.6 - Initiate Inclisiran
                    # Check if has had 6 months of Inclisiran
                    if months_on_inclisiran >= 6:
                        # Check LDL again
                        if ldl_cholesterol > 2:
                            # Add Ezetimibe as third line
                            return "Add in Ezetimibe"
                        else:
                            return "No Further Action"
                    else:
                        # Hasn't had 6 months - Repeat Lipids at 3 months or Initiate
                        if months_on_inclisiran > 0:
                            return "Repeat Lipids at 3 months"
                        else:
                            return "Initiate Inclisiran"
                else:
                    return "No Further Action"
            else:
                # Not on maximally tolerated statin
                return "Send Lipid Lowering Therapy AccuRx with self booking link"
        
        elif prevention_type == "Primary":
            # Primary prevention - check if taking lipid lowering therapy
            if taking_lipid_lowering_therapy:
                if optimised_on_treatment:
                    return "Mark as No Further Action"
                else:
                    return "Send Lipid Lowering Therapy AccuRx with self booking link"
            else:
                # Not taking lipid lowering therapy - Calculate QRISK
                if qrisk2_3_score >= 10:
                    return "Send Lipid Lowering Therapy AccuRx with self booking link"
                else:
                    return "Send High Cholesterol - Low QRISK AccuRx with self booking link"
        else:
            return "Mark as Satisfactory"