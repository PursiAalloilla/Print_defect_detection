# Print_defect_detection
An exploration to how decision making model could be used to automate vision based calibration task

# Removing the need for human-in-loop calibration for print fine tuning
Most commercial 3D-printers still require human in the loop for some fine tune adjustments to combat certain print defects that can only be detected via vision. This 
Some of these print defects are:
- stringing
- corner blobs
- layer lines

Some 3D-printer companies are trying to solve these problems with external sensor such as load cells etc. but these often are custom built solutions for certain extruder/printer types. 

# Solution

Most modern printers already contain camera modules for print failure detection and so I set out to explore how well multi-modal decision making models could be used for:

  **1. anomaly detection from calibration part (benchy, stringing/extrusion tower)**
  
   methodology:
       Gemini Decisions 1 for
        -Detection (noul)
        -Severity approximation (score)
  **2. adjustment step reasonning from the results**
      "What should the new K value be for combating corner blobs caused by misaligned pressure advance value?"


**Future work**
I was unable to test the control loop in practice as the hackathon only had stock printers available. I deliberately chose Klipper as the target software, for its role as common manufacturer-agnostic software upgrade made to replace the stock proprietary software on printer old and new alike.

One possible way for automated adjustment would be to use the open-source moonraker-project which exposes useful api's for data transfer.


### Made for Junction -26 
