[llm usage examples]

# Example 
- Situation: after selecting multiple Iq.dat files
- Input: "plot selected files in log-log scale" 
- Expected output: 
    - make plot in log-log scale
    
# Example 
- Situation: after selecting multiple Iq.dat files
- Input: "plot selected files in log-lin scale" 
- Expected output: 
    - make plot in log-lin scale   
    
# Example 
- Situation: after selecting multiple txt or dat files, that you don't know if they are iq or general ascii data file
- Input: "plot selected files" 
- Expected output: 
    - read files. identify if first 1 or 2 rows are labels or just for information
    - smartly identify delimiters too. 
    - consider first column be x value. second column be y value. 
    - make plot in lin-lin scale. 
    
# Example 
- Situation: after selecting multiple txt or dat files, that you don't know if they are iq or general ascii data file
- Input: "plot selected files in lin-log scale. let x axis label be time, y axis label be the viscocity" 
- Expected output: 
    - read files. identify if first 1 or 2 rows are labels or just for information
    - smartly identify delimiters too. 
    - consider first column be x value. second column be y value. 
    - make plot in lin-log scale. 
    - add labels as directed
    
    

